#!/usr/bin/env python3
"""EA 交易台：讓 AI（Claude、Grok 或任何能呼叫 MCP 工具或執行指令的 AI）依 BTC / ETH / SOL 的 EA 下單。

只用 Python 標準函式庫（3.10+），不需要安裝任何套件。

分工
- EA 引擎：每個幣一個「無金鑰」的 Freqtrade dry-run 機器人（desk/ea_engine.py 啟動），跑凍結參數的 EA 與 FreqAI，
  REST API 只聽 127.0.0.1。引擎不碰任何交易所帳戶，只提供「該進場 / 停損移到哪 / 該出場」。
- 交易台（本檔）：比對引擎持倉與 AI 的帳本，每個幣產生一條指令；下單前的風控；記錄成交與停損移動。
- AI：在使用者的交易所（USDT 永續合約或現貨，依每個幣的 market）開倉、掛停損、移動停損，然後呼叫 record 記錄。
  PAPER 模式只記錄、不下單。合約 EA 可做多（long）也可做空（short），一律逐倉、用指令給的槓桿。

指令 action（side = long / short）
  OPEN        引擎已進場、AI 沒有部位、價格沒有追太遠、風控通過 → 市價開倉 qty（做多或做空），立刻掛停損 stop_price
  HOLD        兩邊都有同一筆部位，停損一致 → 不動作（確認交易所停損單還在）
  MOVE_STOP   引擎的吊燈停損往有利方向移動 ≥ stop_move_min_pct → 把交易所停損單改到 stop_price
              （多單只會往上、空單只會往下）
  CLOSE       引擎已出場（趨勢轉向 / BTC 轉向 / 停損）或沒有這筆持倉 → 取消停損單、市價平倉全部
  CLOSE_NOW   參考價已穿過帳本停損 → 交易所停損應已觸發；確認，還沒成交就市價平倉
  MISSED      引擎在場內但價格超過追價上限、已穿過停損，或這筆已平倉 → 不追，等下一筆
  WAIT        兩邊都空手
  SHADOW      未通過驗證的 EA → 只看不做
  BLOCKED     風控擋新單（HALT、守衛 HALT、累計虧損上限、金額太小…）→ 不開倉
  ENGINE_DOWN 引擎連不上 / 停擺 / 不是 dry-run / 策略不符 → 不開新倉、不移停損；既有部位保留交易所停損單
  ERROR       帳本異常（同一幣兩筆部位）→ 不動作，回報使用者

使用者才能做的事（需要互動式終端機）：開啟實盤 `live on`、解除暫停 `resume`、修改設定檔。
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
HOME = Path(os.environ.get("EA_HOME") or Path.home() / ".freqai-ea")
DEFAULTS = HERE / "config.json"
FILES = {k: HOME / v for k, v in {
    "config": "config.json", "api": "api.json", "live": "live.json", "halt": "halt.json", "ledger": "ledger.csv",
    "stops": "stops.json", "latest": "signals_latest.json", "history": "signals_history.jsonl", "checks": "checks.jsonl",
    "journal": "journal.jsonl", "guard": "guard/latest.json"}.items()}
PREFIX = "EA-"
FIELDS = ["ts_utc", "execution", "position_id", "coin", "pair", "market", "side", "leverage", "action", "qty", "price",
          "fee_usdt", "funding_usdt", "stop_price", "realized_pnl_usdt", "reason", "note"]
ACTIONABLE = ("OPEN", "MOVE_STOP", "CLOSE", "CLOSE_NOW", "ERROR")
CONFIRM_LIVE = "ENABLE EA LIVE"
CONFIRM_RESUME = "RESUME EA"


# ----------------------------------------------------------------- basics
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat(timespec="seconds")


def _f(x, d=None):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


def _load(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config() -> dict:
    """預設值（desk/config.json）+ 使用者覆寫（$EA_HOME/config.json）。"""
    return _merge(_load(DEFAULTS, {}), _load(FILES["config"], {}) or {})


def _coin(c) -> str:
    return str(c or "").lower().replace("/usdt", "").replace("usdt", "").strip("/- ")


def journal(kind: str, data: dict) -> dict:
    rec = {"at": _iso(), "kind": kind, "ea_mode": ea_mode(), **data}
    _append(FILES["journal"], rec)
    return rec


# ----------------------------------------------------------------- mode (user-controlled)
def live_switch() -> dict:
    s = _load(FILES["live"], {}) or {}
    return {**s, "enabled": bool(s.get("enabled"))}


def halt_state() -> dict:
    s = _load(FILES["halt"], {}) or {}
    return {**s, "halted": bool(s.get("halted"))}


def ea_mode() -> str:
    if halt_state()["halted"]:
        return "HALT"
    return "LIVE" if live_switch()["enabled"] else "PAPER"


def halt(reason: str, by: str = "agent") -> dict:
    """停止所有新進場（任何人、任何 AI 都可以按）。既有部位照停損與出場指令管理。只有使用者能解除。"""
    s = {"halted": True, "reason": reason or "未說明", "at": _iso(), "by": by}
    _save(FILES["halt"], s)
    journal("halt", s)
    return {"ok": True, **s, "resume": "只有使用者能解除：python desk/ea_desk.py resume（互動確認）"}


# ----------------------------------------------------------------- engine (Freqtrade REST API, key-less dry-run)
_NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http(url: str, auth=None, timeout: float = 6.0, proxy: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": "freqai-ea-desk/1.0", "Accept": "application/json"})
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    opener = urllib.request.build_opener() if proxy else _NOPROXY
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _auth() -> tuple[str, str]:
    u, p = os.environ.get("EA_ENGINE_USER"), os.environ.get("EA_ENGINE_PASSWORD")
    if u and p:
        return u, p
    c = _load(FILES["api"], {}) or {}
    return c.get("username", ""), c.get("password", "")


def engine_url(coin: str, cfg: dict) -> str:
    return (os.environ.get(f"EA_ENGINE_{coin.upper()}_URL") or cfg.get("url") or f"http://127.0.0.1:{cfg['port']}").rstrip("/")


def position_id(coin: str, trade: dict) -> str:
    ts = trade.get("open_timestamp") or trade.get("open_fill_timestamp") or 0
    stamp = datetime.fromtimestamp(ts / 1000, timezone.utc).strftime("%Y%m%d%H") if ts else "0"
    return f"{PREFIX}{coin.upper()}-{trade.get('trade_id')}-{stamp}"


def engine(coin: str, d: dict | None = None, timeout: float = 6.0) -> dict:
    """引擎狀態：usable = 連得上且沒有 problems；trade = 目前持倉（含 alloc 與停損）；closed = 最近平倉。"""
    d = d or config()
    cfg = d["coins"][coin]
    base = engine_url(coin, cfg)
    out = {"coin": coin, "url": base, "ok": False, "problems": [], "trade": None, "closed": []}
    auth = _auth()
    if not all(auth):
        out["error"] = "沒有引擎 API 帳密：使用者先執行 python desk/ea_engine.py start"
        return out
    api = base + "/api/v1"
    try:
        conf, health = _http(api + "/show_config", auth, timeout), _http(api + "/health", auth, timeout)
        bal, status = _http(api + "/balance", auth, timeout), _http(api + "/status", auth, timeout)
        trades = _http(api + "/trades?" + urllib.parse.urlencode({"limit": 50}), auth, timeout).get("trades", [])
    except Exception as e:  # noqa: BLE001 - any failure means the engine is unusable
        out["error"] = f"{e.__class__.__name__}: {e}"
        return out
    out["ok"] = True
    pair = cfg["pair"]
    if conf.get("dry_run") is not True:
        out["problems"].append("引擎不是 dry-run：EA 引擎必須無金鑰、只產生訊號，否則會和 AI 重複下單")
    if conf.get("strategy") != cfg["strategy"]:
        out["problems"].append(f"策略不符：引擎跑 {conf.get('strategy')}，應為 {cfg['strategy']}")
    state = str(conf.get("state", "")).lower()
    if "running" not in state and "paused" not in state:
        out["problems"].append(f"引擎狀態 {conf.get('state')}（未運行）")
    last = _f(health.get("last_process_ts"))
    age = (_now().timestamp() - last) / 60 if last else None
    stale = float(d.get("engine_stale_minutes", 20))
    if age is None or age > stale:
        out["problems"].append(f"引擎超過 {stale:g} 分鐘沒有處理 K 線（last_process_ts={last}）")
    out.update({"state": conf.get("state"), "strategy": conf.get("strategy"), "dry_run": conf.get("dry_run"),
                "last_process_age_min": round(age, 1) if age is not None else None,
                "bot_equity": _f(bal.get("total_bot"), _f(bal.get("total")))})
    t = next((x for x in status if x.get("pair") == pair and x.get("is_open", True)), None)
    if t:
        stake = _f(t.get("stake_amount"), 0.0)
        unreal = _f(t.get("total_profit_abs"), _f(t.get("profit_abs"), 0.0))
        eq_entry = (out["bot_equity"] or 0.0) - unreal
        stake = stake * (_f(t.get("leverage"), 1.0) or 1.0)  # margin x leverage = notional: alloc is a notional share
        out["trade"] = {
            "trade_id": t.get("trade_id"), "position_id": position_id(coin, t), "open_date": t.get("open_date"),
            "open_rate": _f(t.get("open_rate")), "amount": _f(t.get("amount")), "stake_amount": stake,
            "alloc": round(min(max(stake / eq_entry, 0.0), 1.0), 4) if eq_entry > 0 else None,
            "stop": _f(t.get("stop_loss_abs")), "initial_stop": _f(t.get("initial_stop_loss_abs")),
            "current_rate": _f(t.get("current_rate")), "enter_tag": t.get("enter_tag"),
            "side": "short" if t.get("is_short") else "long", "leverage": _f(t.get("leverage"), 1.0),
            "liquidation_price": _f(t.get("liquidation_price")),
        }
        if not out["trade"]["alloc"] or not out["trade"]["stop"] or not out["trade"]["open_rate"]:
            out["problems"].append("引擎持倉缺少 alloc、進場價或停損價")
    closed = sorted([x for x in trades if not x.get("is_open") and x.get("pair") == pair],
                    key=lambda x: x.get("close_timestamp") or 0)
    out["closed"] = [{"position_id": position_id(coin, x), "close_date": x.get("close_date"),
                      "close_rate": _f(x.get("close_rate")), "exit_reason": x.get("exit_reason"),
                      "profit_ratio": _f(x.get("profit_ratio"))} for x in closed[-10:]]
    return out


def usable(eng: dict) -> bool:
    return bool(eng.get("ok")) and not eng.get("problems")


def ref_price(pair: str) -> float | None:
    """參考價：OKX 最新成交價（永續 BTC/USDT:USDT 用 SWAP、現貨用現貨），失敗改用 Binance（公開 API、不需金鑰）。
    下單仍以交易所頁面的價格為準。"""
    base, quote = pair.split("/")
    perp = ":" in quote
    quote = quote.split(":")[0]
    sources = ((f"https://www.okx.com/api/v5/market/ticker?instId={base}-{quote}-SWAP", lambda j: j["data"][0]["last"]),
               (f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={base}{quote}", lambda j: j["price"])) if perp else \
              ((f"https://www.okx.com/api/v5/market/ticker?instId={base}-{quote}", lambda j: j["data"][0]["last"]),
               (f"https://api.binance.com/api/v3/ticker/price?symbol={base}{quote}", lambda j: j["price"]))
    for url, pick in sources:
        try:
            v = _f(pick(_http(url, timeout=5, proxy=True)))
            if v:
                return v
        except Exception:  # noqa: BLE001
            continue
    return None


def guard() -> dict:
    """EA 守衛（maintenance/ea_guard.py live）的最新判定。"""
    g = _load(FILES["guard"], {}) or {}
    return {"generated_at": g.get("generated_at"),
            "coins": {k.split("_")[0]: {"status": v.get("status"), "action": v.get("action"), "baseline": k}
                      for k, v in (g.get("coins") or {}).items()}}


# ----------------------------------------------------------------- ledger
def rows() -> list[dict]:
    if not FILES["ledger"].exists():
        return []
    with FILES["ledger"].open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _ledger_append(row: dict) -> dict:
    p = FILES["ledger"]
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    if not new:
        with p.open(newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), [])
        if header != FIELDS:  # older ledger layout: rewrite once with the current columns
            old = rows()
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                w.writerows({k: o.get(k) or ("long" if k == "side" else "") for k in FIELDS} for o in old)
    r = {k: row.get(k, "") for k in FIELDS}
    r["ts_utc"] = r["ts_utc"] or _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(r)
    return r


def held() -> dict[str, list[dict]]:
    pos: dict[str, dict] = {}
    for r in rows():
        if r["action"] == "OPEN":
            pos[r["position_id"]] = r
        elif r["action"] == "CLOSE":
            pos.pop(r["position_id"], None)
    out: dict[str, list[dict]] = {}
    for r in pos.values():
        out.setdefault(r["coin"], []).append(r)
    return out


def closed_ids() -> set[str]:
    return {r["position_id"] for r in rows() if r["action"] == "CLOSE"}


def loss_from_peak(coin: str, execution: str) -> float:
    """這個幣在目前模式（PAPER 或 LIVE）下，已實現損益從高點回落了多少 USDT。"""
    cum = peak = 0.0
    for r in rows():
        if r["coin"] == coin and r["action"] == "CLOSE" and r["execution"] == execution:
            cum += _f(r["realized_pnl_usdt"], 0.0)
            peak = max(peak, cum)
    return peak - cum


def stops() -> dict:
    return _load(FILES["stops"], {}) or {}


def current_stop(pos: dict) -> float | None:
    return _f(stops().get(pos["position_id"], {}).get("stop"), _f(pos.get("stop_price")))


def _set_stop(pid: str, stop: float, how: str) -> None:
    s = stops()
    s[pid] = {"stop": stop, "at": _iso(), "by": how}
    _save(FILES["stops"], s)


def side_of(pos: dict) -> str:
    return "short" if str(pos.get("side") or "long").lower() == "short" else "long"


def through(price: float, stop: float, side: str) -> bool:
    """價格是否已穿過停損（多單：跌到停損以下；空單：漲到停損以上）。"""
    return price >= stop if side == "short" else price <= stop


def better_stop(new: float, old: float, side: str, min_pct: float = 0.0) -> bool:
    """new 是否比 old 更有利至少 min_pct%（多單往上、空單往下）。"""
    return new < old * (1 - min_pct / 100) if side == "short" else new > old * (1 + min_pct / 100)


def market_of(cfg: dict) -> str:
    return "perp" if cfg.get("market") == "perp" or ":" in cfg.get("pair", "") else "spot"


# ----------------------------------------------------------------- sizing and risk
def size(alloc: float, price: float, stop: float, capital: float, d: dict, side: str = "long",
         market: str = "spot", leverage: float = 1.0) -> dict:
    """數量 = EA 的部位比例 alloc × 這個 EA 的資金 / 價格，再限制：單筆風險 ≤ max_risk_pct_of_capital、名目金額 ≤ 資金。
    槓桿不放大部位，只決定佔用的保證金（名目 / 槓桿）。"""
    fee = float(d.get("fee_perp", 0.0005) if market == "perp" else d.get("fee", 0.001))
    per_unit = abs(price - stop) + price * 2 * fee
    q = {"ea_alloc": alloc * capital / price,
         "risk_cap": capital * float(d["max_risk_pct_of_capital"]) / 100 / per_unit if per_unit > 0 else 0.0,
         "capital_cap": capital / price}
    lim = min(q, key=q.get)
    qty = max(q[lim], 0.0)
    lev = max(float(leverage or 1.0), 1.0)
    return {"qty": qty, "side": side, "notional_usdt": round(qty * price, 4), "risk_usdt": round(qty * per_unit, 4),
            "risk_pct_of_capital": round(qty * per_unit / capital * 100, 3) if capital else None,
            "leverage": lev, "margin_usdt": round(qty * price / lev, 4),
            "capital_usdt": capital, "alloc": alloc, "limited_by": lim, "fee": fee}


def _check(coin: str, qty: float | None, price: float | None, d: dict, eng: dict, hold: dict, closed: set, gd: dict) -> dict:
    cfg = d["coins"].get(coin)
    if not cfg:
        return {"approved": False, "coin": coin, "reasons": [f"未知幣種 {coin}"]}
    reasons: list[str] = []
    em = ea_mode()
    if not cfg.get("tradable"):
        reasons.append(f"{coin.upper()} EA 未通過驗證，只做影子紀錄（{cfg.get('validation')}）")
    if em == "HALT":
        reasons.append(f"交易台暫停（HALT）：{halt_state().get('reason')}；只有使用者能解除")
    if (gd.get("coins") or {}).get(coin, {}).get("status") == "HALT":
        reasons.append("EA 守衛判定 HALT（表現超出驗證過的正常範圍）：停止新進場，等人工檢查")
    capital = _f(cfg.get("capital_usdt"), 0.0)
    if capital <= 0:
        reasons.append("這個 EA 的 capital_usdt 未設定（使用者在 ~/.freqai-ea/config.json 設定）")
    elif em in ("PAPER", "LIVE"):
        lost = loss_from_peak(coin, em)
        if lost >= capital * float(d["max_loss_pct_of_capital"]) / 100:
            reasons.append(f"{coin.upper()} {em} 已實現損益從高點回落 {lost:.2f} USDT ≥ 資金的 {d['max_loss_pct_of_capital']}%：停止新進場，等人工檢查")
    if hold.get(coin):
        reasons.append(f"{coin.upper()} 已有 EA 部位 {hold[coin][0]['position_id']}")
    bt = eng.get("trade") if usable(eng) else None
    if not usable(eng):
        reasons.append("EA 引擎不可用：" + "；".join(eng.get("problems") or [eng.get("error") or "?"]))
    elif not bt:
        reasons.append("EA 引擎目前沒有持倉（沒有進場訊號）")
    elif bt["position_id"] in closed:
        reasons.append(f"{bt['position_id']} 已平倉過，不重複進場")
    out = {"approved": False, "coin": coin, "ea_mode": em, "reasons": reasons, "price": price}
    if not price or price <= 0:
        reasons.append("沒有價格")
        return out
    if not bt or capital <= 0:
        return out
    stop, side = bt["stop"], bt.get("side", "long")
    chase = float(d["max_chase_pct"]) / 100
    max_entry = bt["open_rate"] * (1 - chase if side == "short" else 1 + chase)
    if (price < max_entry) if side == "short" else (price > max_entry):
        reasons.append(f"價格 {price} 超過追價上限 {max_entry:.8g}（引擎{'做空' if side == 'short' else '做多'}進場價 "
                       f"{bt['open_rate']} {'−' if side == 'short' else '+'} {d['max_chase_pct']}%）")
    if through(price, stop, side):
        reasons.append(f"價格 {price} 已穿過停損 {stop}")
    sz = size(bt["alloc"], price, stop, capital, d, side, market_of(cfg), bt.get("leverage") or 1.0) \
        if not through(price, stop, side) else None
    if sz:
        q = sz["qty"] if qty is None else float(qty)
        if q > sz["qty"] * 1.0001:
            reasons.append(f"數量 {q} 超過上限 {sz['qty']:.8f}（{sz['limited_by']}）")
        if q * price < float(d.get("min_order_usdt", 10)):
            reasons.append(f"下單金額 {q * price:.2f} USDT 低於最小金額 {d.get('min_order_usdt', 10)}")
    out.update({"approved": not reasons, "position_id": bt["position_id"], "side": side, "market": market_of(cfg),
                "leverage": bt.get("leverage") or 1.0, "margin_mode": "isolated" if market_of(cfg) == "perp" else None,
                "stop_price": stop, ("min_entry_price" if side == "short" else "max_entry_price"): round(max_entry, 8),
                "sizing": sz})
    return out


def check(coin: str, price: float | None = None, qty: float | None = None) -> dict:
    """下單前的風控（AI 看到交易所價格後、按下買入前呼叫）。price 省略時用 OKX/Binance 參考價。"""
    d, coin = config(), _coin(coin)
    if coin not in d["coins"]:
        return {"approved": False, "coin": coin, "reasons": [f"未知幣種 {coin}，可用 {list(d['coins'])}"]}
    price = _f(price) or ref_price(d["coins"][coin]["pair"])
    out = _check(coin, _f(qty), price, d, engine(coin, d), held(), closed_ids(), guard())
    _append(FILES["checks"], {"at": _iso(), "coin": coin, "qty": qty, "price": price, "approved": out["approved"],
                              "position_id": out.get("position_id"), "reasons": out["reasons"]})
    return out


# ----------------------------------------------------------------- instructions
def _instruction(coin: str, cfg: dict, eng: dict, d: dict, hold: dict, closed: set, gd: dict) -> dict:
    pair = cfg["pair"]
    bt = eng.get("trade") if eng.get("ok") else None
    price = ref_price(pair) or (bt or {}).get("current_rate")
    mk = market_of(cfg)
    ins = {"coin": coin.upper(), "pair": pair, "market": mk, "strategy": cfg["strategy"], "tradable": bool(cfg.get("tradable")),
           "reference_price": price,
           "engine": {"usable": usable(eng), "problems": eng.get("problems", []), "error": eng.get("error"), "trade": bt}}
    rws = hold.get(coin, [])
    if len(rws) > 1:
        return {**ins, "action": "ERROR", "why": f"帳本有 {len(rws)} 筆 {coin.upper()} EA 部位 {[r['position_id'] for r in rws]}，請使用者核對"}
    pos = rws[0] if rws else None
    if pos:
        stop, side = current_stop(pos), side_of(pos)
        p = {"position_id": pos["position_id"], "side": side, "qty": _f(pos["qty"]), "entry_price": _f(pos["price"]),
             "stop_price": stop, "leverage": _f(pos.get("leverage"), 1.0), "execution": pos["execution"]}
        ins["position"] = p
        ins["side"] = side
        if price and stop and through(price, stop, side):
            return {**ins, "action": "CLOSE_NOW", "qty": p["qty"],
                    "why": f"參考價 {price} 已穿過停損 {stop}：交易所停損單應已觸發。到交易所確認；還持有就市價平倉全部，然後 record CLOSE"}
        if not usable(eng):
            return {**ins, "action": "ENGINE_DOWN",
                    "why": "引擎不可用：不移動停損、不開新倉；交易所停損單保留。請使用者修復引擎（python desk/ea_engine.py status）"}
        if bt and bt["position_id"] == pos["position_id"]:
            new = bt["stop"]
            if stop is None or better_stop(new, stop, side, float(d["stop_move_min_pct"])):
                way = "下移" if side == "short" else "上移"
                return {**ins, "action": "MOVE_STOP", "stop_price": new,
                        "why": f"引擎吊燈停損由 {stop} {way}到 {new}：把交易所停損單改到 {new}（只能往有利方向），然後 record STOP"}
            return {**ins, "action": "HOLD", "why": "部位與引擎一致；確認交易所停損單仍在"}
        ex = next((c for c in eng.get("closed", []) if c["position_id"] == pos["position_id"]), None)
        why = f"引擎已於 {ex['close_date']} 以 {ex['close_rate']} 出場（{ex['exit_reason']}）" if ex else "引擎沒有這筆持倉"
        return {**ins, "action": "CLOSE", "qty": p["qty"], "exit_reason": (ex or {}).get("exit_reason") or "engine_flat",
                "why": why + "：取消交易所停損單、市價平倉全部，然後 record CLOSE"}
    if not cfg.get("tradable"):
        return {**ins, "action": "SHADOW", "why": f"未通過驗證，只看不做：{cfg.get('validation')}"}
    if not usable(eng):
        return {**ins, "action": "ENGINE_DOWN", "why": "引擎不可用：" + "；".join(eng.get("problems") or [eng.get("error") or "?"])}
    if not bt:
        return {**ins, "action": "WAIT", "why": "EA 在場外（沒有突破或趨勢不成立）"}
    if bt["position_id"] in closed:
        return {**ins, "action": "MISSED", "why": f"{bt['position_id']} 已平倉過（停損或手動），等引擎下一筆"}
    if not price:
        return {**ins, "action": "WAIT", "why": "沒有參考價，下一輪再看"}
    side = bt.get("side", "long")
    ins["side"] = side
    chase = float(d["max_chase_pct"]) / 100
    limit = bt["open_rate"] * (1 - chase if side == "short" else 1 + chase)
    if (price < limit) if side == "short" else (price > limit):
        return {**ins, "action": "MISSED", "why": f"價格 {price} 已超過追價上限 {limit:.8g}：不追，等下一筆"}
    if through(price, bt["stop"], side):
        return {**ins, "action": "MISSED", "why": f"價格 {price} 已穿過引擎停損 {bt['stop']}：不進場"}
    c = _check(coin, None, price, d, eng, hold, closed, gd)
    if not c["approved"]:
        return {**ins, "action": "BLOCKED", "why": "；".join(c["reasons"]), "risk": c}
    em = ea_mode()
    lev = c.get("leverage") or 1.0
    how = (f"在 USDT 永續合約頁：逐倉、槓桿 {lev:g}x，市價{'做空（賣出開空）' if side == 'short' else '做多（買入開多）'} qty"
           if mk == "perp" else "在現貨市價買入 qty")
    return {**ins, "action": "OPEN", "execution": em, "position_id": c["position_id"], "qty": c["sizing"]["qty"],
            "leverage": lev, "margin_mode": c.get("margin_mode"), "notional_usdt": c["sizing"]["notional_usdt"],
            "margin_usdt": c["sizing"]["margin_usdt"], "stop_price": c["stop_price"],
            **{k: c[k] for k in ("max_entry_price", "min_entry_price") if k in c}, "risk": c["sizing"],
            "why": f"引擎 {bt['open_date']} 以 {bt['open_rate']} {'做空' if side == 'short' else '做多'}（{bt['enter_tag']}）。"
                   + (f"LIVE：先 risk_check（用交易所頁面的價格），通過後{how}（向下取到交易所允許的位數），立刻設停損 stop_price，再 record OPEN"
                      if em == "LIVE" else f"PAPER：不下單，以參考價 record OPEN（LIVE 時的做法：{how}，並設停損 stop_price）")}


def signals(write: bool = True) -> dict:
    """每個幣一條指令（會呼叫引擎與公開報價）。"""
    d = config()
    hold, closed, gd = held(), closed_ids(), guard()
    out = {"at": _iso(), "ea_mode": ea_mode(), "live_switch": live_switch()["enabled"], "halt": halt_state(),
           "guard": gd, "coins": {}}
    for coin, cfg in d["coins"].items():
        try:
            out["coins"][coin] = _instruction(coin, cfg, engine(coin, d), d, hold, closed, gd)
        except Exception as e:  # noqa: BLE001
            out["coins"][coin] = {"coin": coin.upper(), "action": "ENGINE_DOWN", "why": f"{e.__class__.__name__}: {e}"}
    out["todo"] = [f"{k.upper()} {v['action']}" for k, v in out["coins"].items() if v["action"] in ACTIONABLE]
    if write:
        prev = _load(FILES["latest"], {}) or {}
        _save(FILES["latest"], out)
        changed = {k: v["action"] for k, v in out["coins"].items()
                   if (prev.get("coins") or {}).get(k, {}).get("action") != v["action"]}
        if changed:
            _append(FILES["history"], {"at": out["at"], "ea_mode": out["ea_mode"], "changed": changed})
    return out


# ----------------------------------------------------------------- recording
def record(event: str, coin: str = "", position_id: str = "", qty=None, price=None, fee_usdt=None,
           stop_price=None, reason: str = "", note: str = "", side: str = "", leverage=None, funding_usdt=None) -> dict:
    """event: OPEN | CLOSE | STOP | SKIP。實際成交一定要記（即使違反規則也記並附警告），帳本才會和交易所一致。"""
    event = str(event).upper()
    d = config()
    coin = _coin(coin) or (position_id.split("-")[1].lower() if position_id.startswith(PREFIX) else "")
    if coin not in d["coins"]:
        return {"ok": False, "error": f"需要 coin（{list(d['coins'])}）或 EA position_id"}
    cfg, hold, warnings = d["coins"][coin], held(), []
    if event == "OPEN":
        qty, price = _f(qty), _f(price)
        if not qty or not price or qty <= 0 or price <= 0:
            return {"ok": False, "error": "OPEN 需要 qty 與 price（實際成交數量與均價；PAPER 用參考價）"}
        if hold.get(coin):
            return {"ok": False, "error": f"{coin.upper()} 已有 EA 部位 {hold[coin][0]['position_id']}；先 CLOSE"}
        bt = engine(coin, d).get("trade")
        pid = position_id or (bt or {}).get("position_id")
        if not pid or not pid.startswith(f"{PREFIX}{coin.upper()}-"):
            return {"ok": False, "error": "缺少 position_id，且引擎沒有持倉可對應（照 signals 給的 position_id 填）"}
        if not bt or bt["position_id"] != pid:
            warnings.append("引擎目前沒有這筆持倉")
        stop = _f(stop_price) or (bt or {}).get("stop")
        if not stop:
            return {"ok": False, "error": "需要 stop_price（交易所停損單的觸發價）"}
        sd = (str(side).lower() or (bt or {}).get("side") or "long")
        if sd not in ("long", "short"):
            return {"ok": False, "error": "side 必須是 long 或 short"}
        if bt and bt.get("side") and sd != bt["side"]:
            warnings.append(f"方向 {sd} 與引擎 {bt['side']} 不同：請立即核對交易所部位")
        if market_of(cfg) == "spot" and sd == "short":
            return {"ok": False, "error": "現貨 EA 不能做空"}
        if through(price, stop, sd):
            warnings.append(f"成交價 {price} 已穿過停損 {stop}")
        lev = _f(leverage) or (bt or {}).get("leverage") or 1.0
        em = ea_mode()
        if em == "LIVE":
            recent = [json.loads(x) for x in FILES["checks"].read_text(encoding="utf-8").splitlines()[-50:]] \
                if FILES["checks"].exists() else []
            if not any(c["coin"] == coin and c["approved"] and c.get("position_id") == pid
                       and (_now() - datetime.fromisoformat(c["at"])).total_seconds() < 1800 for c in recent):
                warnings.append("30 分鐘內沒有通過的 risk_check：違反作業手冊，請回報使用者")
        if em == "HALT":
            warnings.append("HALT 期間開倉：違反作業手冊，請回報使用者")
            em = "LIVE" if live_switch()["enabled"] else "PAPER"
        row = _ledger_append({"execution": em, "position_id": pid, "coin": coin, "pair": cfg["pair"], "market": market_of(cfg),
                              "side": sd, "leverage": lev, "action": "OPEN",
                              "qty": qty, "price": price, "fee_usdt": _f(fee_usdt, 0.0), "stop_price": stop,
                              "reason": reason or f"EA {cfg['strategy']} {(bt or {}).get('enter_tag') or 'breakout'}",
                              "note": note})
        _set_stop(pid, stop, "OPEN")
        journal("fill", {**row, "warnings": warnings})
        return {"ok": True, "position_id": pid, "execution": em, "side": sd, "leverage": lev, "stop_price": stop,
                "warnings": warnings}
    rws = hold.get(coin, [])
    pos = next((r for r in rws if r["position_id"] == position_id), rws[0] if rws else None)
    if event == "STOP":
        if not pos:
            return {"ok": False, "error": f"{coin.upper()} 沒有 EA 部位"}
        new, old = _f(stop_price), current_stop(pos)
        if not new or new <= 0:
            return {"ok": False, "error": "STOP 需要 stop_price"}
        if old and new != old and not better_stop(new, old, side_of(pos)):
            return {"ok": False, "error": f"停損只能往有利方向移動（{'空單往下' if side_of(pos) == 'short' else '多單往上'}；"
                                         f"目前 {old}，收到 {new}）"}
        _set_stop(pos["position_id"], new, "MOVE")
        journal("stop", {"position_id": pos["position_id"], "from": old, "to": new})
        return {"ok": True, "position_id": pos["position_id"], "stop_from": old, "stop_to": new}
    if event == "CLOSE":
        if not pos:
            return {"ok": False, "error": f"{coin.upper()} 沒有 EA 部位"}
        price = _f(price)
        if not price or price <= 0:
            return {"ok": False, "error": "CLOSE 需要 price（實際成交均價；PAPER 用參考價或停損價）"}
        q_open = _f(pos["qty"], 0.0)
        q = _f(qty, q_open)
        if q > q_open * 1.0001:
            return {"ok": False, "error": f"平倉數量 {q} 大於部位 {q_open}"}
        if q < q_open * 0.98:
            warnings.append(f"只平倉 {q}/{q_open}，帳本視為全部平倉；剩餘數量請使用者處理")
        fee_c = _f(fee_usdt, 0.0)
        fee_o = _f(pos["fee_usdt"], 0.0) * q / q_open if q_open else 0.0
        fund = _f(funding_usdt, 0.0)  # + received, - paid (from the exchange's funding history)
        sign = -1.0 if side_of(pos) == "short" else 1.0
        pnl = sign * q * (price - _f(pos["price"], 0.0)) - fee_o - fee_c + fund
        row = _ledger_append({"execution": pos["execution"], "position_id": pos["position_id"], "coin": coin,
                              "pair": cfg["pair"], "market": pos.get("market") or market_of(cfg), "side": side_of(pos),
                              "leverage": pos.get("leverage") or "", "action": "CLOSE", "qty": q, "price": price,
                              "fee_usdt": fee_c, "funding_usdt": fund,
                              "stop_price": current_stop(pos), "realized_pnl_usdt": round(pnl, 6),
                              "reason": reason or "exit", "note": note})
        s = stops()
        s.pop(pos["position_id"], None)
        _save(FILES["stops"], s)
        journal("fill", {**row, "warnings": warnings})
        return {"ok": True, "position_id": pos["position_id"], "execution": pos["execution"],
                "realized_pnl_usdt": round(pnl, 4), "warnings": warnings}
    if event == "SKIP":
        journal("skip", {"coin": coin.upper(), "position_id": position_id, "reason": reason or note})
        return {"ok": True}
    return {"ok": False, "error": "event 必須是 OPEN / CLOSE / STOP / SKIP"}


# ----------------------------------------------------------------- overview
def status() -> dict:
    d = config()
    engines = {}
    for coin in d["coins"]:
        e = engine(coin, d)
        engines[coin] = {k: e.get(k) for k in ("url", "ok", "problems", "error", "state", "strategy", "dry_run",
                                               "last_process_age_min", "trade")}
    pos = {c: [{"position_id": r["position_id"], "side": side_of(r), "qty": _f(r["qty"]), "entry": _f(r["price"]),
                "stop": current_stop(r), "leverage": _f(r.get("leverage"), 1.0), "execution": r["execution"]}
               for r in rs] for c, rs in held().items()}
    pnl: dict[str, dict] = {}
    for r in rows():
        if r["action"] == "CLOSE":
            k = pnl.setdefault(f"{r['coin']}_{r['execution']}", {"trades": 0, "realized_pnl_usdt": 0.0})
            k["trades"] += 1
            k["realized_pnl_usdt"] = round(k["realized_pnl_usdt"] + _f(r["realized_pnl_usdt"], 0.0), 4)
    return {"ea_mode": ea_mode(), "live_switch": live_switch(), "halt": halt_state(), "home": str(HOME),
            "settings": {k: d.get(k) for k in ("venue_note", "max_chase_pct", "stop_move_min_pct", "max_risk_pct_of_capital",
                                           "max_loss_pct_of_capital", "min_order_usdt")},
            "coins": {c: {"market": market_of(v), **{k: v.get(k) for k in ("strategy", "pair", "tradable", "capital_usdt", "validation")}}
                      for c, v in d["coins"].items()},
            "engines": engines, "positions": pos, "closed_pnl": pnl, "guard": guard(),
            "last_signals_at": (_load(FILES["latest"], {}) or {}).get("at"),
            "user_only": {"start_engine": "python desk/ea_engine.py start", "enable_live": "python desk/ea_desk.py live on",
                          "resume_after_halt": "python desk/ea_desk.py resume", "settings": str(FILES["config"])},
            "guide": "AGENTS.md（或 MCP 工具 ea_guide）"}


def guide() -> str:
    return (SKILL / "AGENTS.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------- CLI
def _interactive(prompt_lines: list[str], phrase: str) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("拒絕：必須由使用者在互動式終端機執行（AI 與排程不能做這件事）。")
        return False
    print("\n".join(prompt_lines + [f"確認請輸入：{phrase}"]))
    return input("> ").strip() == phrase


def main() -> int:
    ap = argparse.ArgumentParser(description="EA 交易台（輸出 JSON，給 AI 或人使用）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("signals", help="每個幣的指令")
    sub.add_parser("status", help="模式、引擎、部位、損益")
    sub.add_parser("guide", help="印出 AI 作業手冊 AGENTS.md")
    c = sub.add_parser("check", help="下單前風控")
    c.add_argument("--coin", required=True)
    c.add_argument("--price", type=float)
    c.add_argument("--qty", type=float)
    r = sub.add_parser("record", help="記錄 OPEN / CLOSE / STOP / SKIP")
    r.add_argument("--event", required=True, choices=["OPEN", "CLOSE", "STOP", "SKIP", "open", "close", "stop", "skip"])
    for k in ("coin", "position-id", "reason", "note", "side"):
        r.add_argument(f"--{k}", default="")
    for k in ("qty", "price", "fee-usdt", "stop-price", "leverage", "funding-usdt"):
        r.add_argument(f"--{k}", type=float)
    h = sub.add_parser("halt", help="停止所有新進場（任何人可用）")
    h.add_argument("--reason", default="")
    sub.add_parser("resume", help="解除 HALT（只有使用者，互動確認）")
    lv = sub.add_parser("live", help="實盤開關（on 只有使用者，互動確認）")
    lv.add_argument("what", choices=["on", "off", "status"])
    a = ap.parse_args()

    def show(x) -> int:
        print(json.dumps(x, ensure_ascii=False, indent=2, default=str))
        return 0

    if a.cmd == "signals":
        return show(signals())
    if a.cmd == "status":
        return show(status())
    if a.cmd == "guide":
        print(guide())
        return 0
    if a.cmd == "check":
        return show(check(a.coin, a.price, a.qty))
    if a.cmd == "record":
        return show(record(a.event, a.coin, a.position_id, a.qty, a.price, a.fee_usdt, a.stop_price, a.reason, a.note,
                           a.side, a.leverage, a.funding_usdt))
    if a.cmd == "halt":
        return show(halt(a.reason, by="cli"))
    if a.cmd == "resume":
        if not _interactive([f"解除 HALT（原因：{halt_state().get('reason')}）。確認已檢查過原因。"], CONFIRM_RESUME):
            return 1
        _save(FILES["halt"], {"halted": False, "at": _iso(), "by": "user-terminal"})
        journal("resume", {"by": "user-terminal"})
        return show({"ok": True, "ea_mode": ea_mode()})
    if a.what == "status":
        return show({"ea_mode": ea_mode(), **live_switch()})
    if a.what == "off":
        _save(FILES["live"], {"enabled": False, "at": _iso(), "by": "terminal"})
        journal("live", {"enabled": False})
        return show({"ok": True, "ea_mode": ea_mode(), "note": "之後的新部位都是 PAPER；既有 LIVE 部位照停損/出場指令管理"})
    d = config()
    lines = ["開啟 EA 實盤：AI 之後會在你的交易所現貨真的下單。"]
    lines += [f"- {k.upper()} {v['strategy']}：{'交易' if v['tradable'] else '只做影子紀錄'}，資金 {v['capital_usdt']} USDT"
              for k, v in d["coins"].items()]
    lines += [f"- 單筆風險上限：資金的 {d['max_risk_pct_of_capital']}%（EA 設計：停損一次約虧資金的 10%）。",
              "- 趨勢跟隨：每年約 4–5 筆、勝率 30–50%、大部分時間空手；牛市跑輸持有、熊市不會賺；回測最大回撤約 30%。",
              "- 交易所帳戶要先有足夠 USDT，金鑰（若有）不可開提幣權限。",
              "- 建議先 PAPER ≥ 30 天，確認 AI 的帳本和引擎一致（AGENTS.md 的上線檢查表）。"]
    if not _interactive(lines, CONFIRM_LIVE):
        print("未開啟。")
        return 1
    _save(FILES["live"], {"enabled": True, "at": _iso(), "by": "user-terminal"})
    journal("live", {"enabled": True})
    return show({"ok": True, "ea_mode": ea_mode(), "off": "python desk/ea_desk.py live off"})


if __name__ == "__main__":
    sys.exit(main())
