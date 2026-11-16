#!/usr/bin/env python3
"""AI 交易辦公室（控制台）：在瀏覽器裡看 EA 怎麼運作。

    python3 desk/console.py            # 開 http://127.0.0.1:8765
    python3 desk/console.py --open     # 同時打開瀏覽器

兩種畫面：
- 即時：讀交易台（desk/ea_desk.py）與三個 EA 引擎的 REST API，顯示每個角色正在做什麼——行情、EA 引擎、交易台、
  AI 交易員、交易所、守衛——以及引擎算出的趨勢線、突破／跌破線、止損、部位、帳本與事件紀錄。
- 回放：用真實回測資料（desk/console/replays/*.json，由 scripts/replay_build.py 產生）一步步重播策略怎麼運作。

只用 Python 標準函式庫；只聽 127.0.0.1。控制台唯一能改變狀態的動作是「停止新進場」（HALT，任何人都可以按）。
開實盤、解除 HALT 仍然只能在終端機由使用者執行。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ea_desk  # noqa: E402

UI = HERE / "console"
REPLAYS = UI / "replays"
LWC = ea_desk.SKILL / "tradingview" / "node_modules" / "lightweight-charts" / "dist" / "lightweight-charts.standalone.production.js"
CANDLE_COLS = ["ema_slow", "ema_short", "donchian_high", "donchian_low", "sigma_day", "above", "below", "s_below", "s_above",
               "rising", "falling", "risk_on", "risk_off", "bear", "do_predict"]
HEADER = "X-EA-Console"
SKELETON = ('<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n{}\n</body>\n</html>\n')


def page(replay: Path | None = None, fragment: bool = False) -> str:
    """The console page; with `replay`, a standalone replay page (data embedded) that works without the server.
    `fragment` leaves out the <!doctype>/<head>/<body> skeleton (for hosts that add their own)."""
    html = (UI / "index.html").read_text(encoding="utf-8")
    if replay is not None:
        data = replay.read_text(encoding="utf-8").replace("</", "<\\/")
        marker = '<script id="replay-data" type="application/json">null</script>'
        assert marker in html
        html = html.replace(marker, f'<script id="replay-data" type="application/json">{data}</script>')
    return html if fragment else SKELETON.format(html)


def _tail(path: Path, n: int) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def state() -> dict:
    """畫面需要的全部即時資料（讀檔 + 三個引擎的狀態，不呼叫外部報價）。"""
    st = ea_desk.status()
    return {"status": st, "signals": ea_desk._load(ea_desk.FILES["latest"], {}) or {},
            "ledger": ea_desk.rows()[-300:], "journal": _tail(ea_desk.FILES["journal"], 150),
            "history": _tail(ea_desk.FILES["history"], 150), "checks": _tail(ea_desk.FILES["checks"], 20)}


def candles(coin: str, limit: int = 600) -> dict:
    """引擎算好的 1 小時 K 線與指標（Freqtrade POST /pair_candles，只取畫圖需要的欄位）。"""
    d = ea_desk.config()
    coin = ea_desk._coin(coin)
    if coin not in d["coins"]:
        return {"ok": False, "error": f"未知幣種 {coin}"}
    cfg = d["coins"][coin]
    url = ea_desk.engine_url(coin, cfg) + "/api/v1/pair_candles"
    body = json.dumps({"pair": cfg["pair"], "timeframe": "1h", "limit": int(limit), "columns": CANDLE_COLS}).encode()
    u, p = ea_desk._auth()
    if not (u and p):
        return {"ok": False, "error": "沒有引擎 API 帳密：先執行 python3 desk/ea_engine.py start"}
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode())
    try:
        with ea_desk._NOPROXY.open(req, timeout=8) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    return {"ok": True, "coin": coin, "pair": cfg["pair"], "market": ea_desk.market_of(cfg), "columns": res.get("columns", []),
            "data": res.get("data", []), "last_analyzed": res.get("last_analyzed")}


def replays() -> list[dict]:
    out = []
    for f in sorted(REPLAYS.glob("*.json")):
        try:
            with f.open(encoding="utf-8") as fh:
                head = json.loads(fh.read())
            out.append({"name": f.stem, "title": head.get("title"), "bar": head.get("bar"),
                        "coins": [c["label"] for c in head.get("coins", [])]})
        except Exception:  # noqa: BLE001
            continue
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "EAConsole/1.0"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        try:
            if url.path in ("/", "/index.html"):
                return self._send(200, page().encode("utf-8"), "text/html; charset=utf-8")
            if url.path == "/lib/lightweight-charts.js":
                if LWC.exists():
                    return self._send(200, LWC.read_bytes(), "application/javascript")
                return self._send(404, b"", "text/plain")
            if url.path == "/api/ping":
                return self._json({"ok": True, "console": True})
            if url.path == "/api/state":
                return self._json(state())
            if url.path == "/api/signals":
                return self._json(ea_desk.signals())
            if url.path == "/api/candles":
                return self._json(candles(q.get("coin", ""), int(q.get("limit", 600))))
            if url.path == "/api/replays":
                return self._json(replays())
            if url.path == "/api/replay":
                f = REPLAYS / (Path(q.get("name", "")).name + ".json")
                if f.exists():
                    return self._send(200, f.read_bytes(), "application/json; charset=utf-8")
                return self._json({"ok": False, "error": "找不到回放"}, 404)
            return self._json({"ok": False, "error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001 - the console must keep serving
            return self._json({"ok": False, "error": f"{e.__class__.__name__}: {e}"}, 500)

    def do_POST(self):  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if self.headers.get(HEADER) != "1" or (origin and urllib.parse.urlparse(origin).netloc != host):
            return self._json({"ok": False, "error": "拒絕：只接受控制台頁面本身的請求"}, 403)
        if url.path != "/api/halt":
            return self._json({"ok": False, "error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(min(n, 10_000)).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            data = {}
        reason = str(data.get("reason") or "使用者在控制台按下停止新進場")[:300]
        return self._json(ea_desk.halt(reason, by="console"))


def serve(port: int = 8765, open_browser: bool = False) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"AI 交易辦公室：{url}（Ctrl+C 結束）")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 交易辦公室（控制台）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="打開瀏覽器")
    ap.add_argument("--export", metavar="OUT.html", help="匯出單一檔案的回放頁（不需要伺服器），例如分享給別人看")
    ap.add_argument("--replay", default="bear-2025-26", help="--export 用的回放名稱（desk/console/replays/<名稱>.json）")
    ap.add_argument("--fragment", action="store_true", help="--export 時不加 HTML 骨架（給會自己加骨架的網頁空間用）")
    a = ap.parse_args()
    if a.export:
        Path(a.export).write_text(page(REPLAYS / f"{a.replay}.json", a.fragment), encoding="utf-8")
        print(f"已匯出 {a.export}")
        return 0
    srv = serve(a.port, a.open)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
