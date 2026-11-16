#!/usr/bin/env python3
"""AI 交易辦公室（控制台）測試：模擬三個 Freqtrade 引擎，啟動 console.py 伺服器，檢查頁面、API 與安全限制。

    python3 skills/freqai-ea-trading/desk/test_console.py           # 跑測試
    python3 skills/freqai-ea-trading/desk/test_console.py --keep    # 跑完不關，開瀏覽器看即時畫面（模擬資料）

不需要網路、Freqtrade 或任何套件；用暫存的 EA_HOME。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ea-console-test-")
os.environ["EA_HOME"] = TMP
os.environ["EA_ENGINE_USER"], os.environ["EA_ENGINE_PASSWORD"] = "u", "p"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import console  # noqa: E402
import ea_desk  # noqa: E402

NOW = int(time.time())
PRICES = {"BTC/USDT": 96000.0, "ETH/USDT:USDT": 2950.0, "SOL/USDT:USDT": 140.0}
ea_desk.ref_price = lambda pair: PRICES.get(pair)
STRATS = {"btc": "BTCTrendEA", "eth": "ETHFuturesEA", "sol": "SOLFuturesEA"}
BOTS: dict[str, dict] = {}


def candles(pair: str, base: float, n: int = 120) -> dict:
    cols = ["date", "open", "high", "low", "close", "volume", "ema_slow", "ema_short", "donchian_high", "donchian_low",
            "sigma_day", "enter_long", "enter_short"]
    rows = []
    for k in range(n):
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(NOW - (n - k) * 3600))
        px = base * (1 - 0.0008 * k)
        rows.append([t + "+00:00", px, px * 1.004, px * 0.996, px * 0.999, 100.0, base * 1.05, base * 1.04, base * 1.08,
                     base * 0.93, 0.03, 0, 1 if k == n - 5 else 0])
    return {"pair": pair, "timeframe": "1h", "columns": cols, "data": rows, "last_analyzed": "now"}


class Bot(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok(self):
        return self.headers.get("Authorization") == "Basic " + base64.b64encode(b"u:p").decode()

    def _send(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):  # noqa: N802
        if not self._ok():
            return self._send({}, 401)
        b = BOTS[self.server.coin]
        path = self.path.split("?")[0].replace("/api/v1", "")
        body = {"/show_config": b["conf"], "/health": {"last_process_ts": int(time.time())}, "/balance": {"total_bot": 10000.0},
                "/status": b["status"], "/trades": {"trades": []}}.get(path)
        self._send(body, 200 if body is not None else 404)

    def do_POST(self):  # noqa: N802
        if not self._ok():
            return self._send({}, 401)
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        if self.path.endswith("/pair_candles"):
            BOTS[self.server.coin]["last_candle_request"] = req
            return self._send(candles(req["pair"], PRICES.get(req["pair"], 100.0) * 1.08))
        self._send({}, 404)


for coin, strat in STRATS.items():
    BOTS[coin] = {"conf": {"dry_run": True, "strategy": strat, "state": "running"}, "status": []}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Bot)
    srv.coin = coin
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ[f"EA_ENGINE_{coin.upper()}_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
BOTS["eth"]["status"] = [{"trade_id": 4, "pair": "ETH/USDT:USDT", "is_open": True, "is_short": True, "leverage": 2.0,
                          "open_rate": 3000.0, "amount": 1.0, "stake_amount": 1500.0, "stop_loss_abs": 3210.0,
                          "initial_stop_loss_abs": 3210.0, "open_timestamp": (NOW - 7200) * 1000, "open_date": "x",
                          "current_rate": 2950.0, "enter_tag": "breakdown", "profit_abs": 0, "total_profit_abs": 0}]

CON = console.serve(0)
threading.Thread(target=CON.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{CON.server_address[1]}"
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
RESULTS: list[bool] = []


def ok(cond, name, info="") -> None:
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))


def get(path):
    with NOPROXY.open(BASE + path, timeout=10) as r:
        return r.status, r.read()


def post(path, body, headers):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with NOPROXY.open(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


code, html = get("/")
ok(code == 200 and html.startswith(b"<!doctype html>") and "<title>AI 交易辦公室</title>".encode() in html, "首頁有完整 HTML 骨架與標題")
ok(json.loads(get("/api/ping")[1]).get("console") is True, "/api/ping")
sig = json.loads(get("/api/signals")[1])
ok(sig["coins"]["eth"]["action"] == "OPEN" and sig["coins"]["eth"]["side"] == "short", "/api/signals：ETH 引擎做空 → OPEN short",
   sig["coins"]["eth"].get("why"))
st = json.loads(get("/api/state")[1])
ok(st["status"]["engines"]["eth"]["ok"] and st["signals"]["coins"]["eth"]["action"] == "OPEN", "/api/state 帶引擎狀態與最新指令")
ok(st["status"]["coins"]["eth"]["market"] == "perp" and st["status"]["coins"]["btc"]["market"] == "spot", "/api/state 標示合約 / 現貨")
cd = json.loads(get("/api/candles?coin=eth")[1])
ok(cd["ok"] and "ema_short" in cd["columns"] and len(cd["data"]) == 120, "/api/candles 取得引擎的 K 線與指標", cd.get("error"))
req = BOTS["eth"].get("last_candle_request", {})
ok(req.get("pair") == "ETH/USDT:USDT" and "donchian_low" in (req.get("columns") or []), "/api/candles 只向引擎要畫圖需要的欄位", req)
rl = json.loads(get("/api/replays")[1])
ok(any(r["name"] == "bear-2025-26" for r in rl), "/api/replays 列出回放", rl)
code, body = get("/api/replay?name=bear-2025-26")
ok(code == 200 and len(json.loads(body)["coins"]) == 3, "/api/replay 回傳三個幣的回放")
try:
    code = get("/api/replay?name=../config")[0]
except urllib.error.HTTPError as e:
    code = e.code
ok(code == 404, "回放名稱不能跳出資料夾", code)
code, r = post("/api/halt", {"reason": "x"}, {})
ok(code == 403 and ea_desk.ea_mode() != "HALT", "沒有控制台標頭的 POST 被拒", (code, r))
code, r = post("/api/halt", {"reason": "x"}, {"X-EA-Console": "1", "Origin": "https://evil.example"})
ok(code == 403 and ea_desk.ea_mode() != "HALT", "其他網站來源的 POST 被拒", (code, r))
code, r = post("/api/halt", {"reason": "控制台測試"}, {"X-EA-Console": "1", "Origin": BASE})
ok(code == 200 and r.get("ok") and ea_desk.ea_mode() == "HALT", "控制台的停止新進場有效", (code, r))
ok(json.loads(get("/api/state")[1])["status"]["halt"]["halted"], "狀態顯示 HALT")
try:
    code = get("/api/nope")[0]
except urllib.error.HTTPError as e:
    code = e.code
ok(code == 404, "未知路徑 404")
exp = console.page(console.REPLAYS / "bear-2025-26.json")
ok('<script id="replay-data" type="application/json">{' in exp and "</script>" in exp, "匯出的單檔回放頁含資料")

print(f"\n{sum(RESULTS)}/{len(RESULTS)} 通過（EA_HOME={TMP}，控制台 {BASE}）")
if "--keep" in sys.argv:
    ea_desk._save(ea_desk.FILES["halt"], {"halted": False})
    print("保持執行中，按 Ctrl+C 結束")
    while True:
        time.sleep(3600)
sys.exit(0 if all(RESULTS) else 1)
