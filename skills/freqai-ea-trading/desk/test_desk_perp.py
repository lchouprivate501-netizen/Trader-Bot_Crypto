#!/usr/bin/env python3
"""EA 交易台合約（永續、多空）測試：模擬 Freqtrade 合約 dry-run 引擎，檢查做空、槓桿、停損方向、資金費與現貨不能做空。

    python3 skills/freqai-ea-trading/desk/test_desk_perp.py

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ea-desk-perp-")
os.environ["EA_HOME"] = TMP
os.environ["EA_ENGINE_USER"], os.environ["EA_ENGINE_PASSWORD"] = "u", "p"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ea_desk  # noqa: E402

OPEN_TS = int((time.time() - 2 * 3600) * 1000)
PRICES = {"BTC/USDT:USDT": 100000.0, "ETH/USDT:USDT": 3000.0, "SOL/USDT:USDT": 149.0, "SOL/USDT": 149.0}
ea_desk.ref_price = lambda pair: PRICES.get(pair)
STRATS = {"btc": "BTCFuturesEA", "eth": "ETHFuturesEA", "sol": "SOLFuturesEA"}
BOTS: dict[str, dict] = {}


def trade(pair, rate, stop, margin, lev=2.0, short=True, tid=11, profit=0.0) -> dict:
    return {"trade_id": tid, "pair": pair, "is_open": True, "is_short": short, "leverage": lev, "open_rate": rate,
            "amount": margin * lev / rate, "stake_amount": margin, "stop_loss_abs": stop, "initial_stop_loss_abs": stop,
            "open_timestamp": OPEN_TS, "open_date": "2026-11-16 06:00:00", "current_rate": rate,
            "enter_tag": "breakdown" if short else "breakout", "profit_abs": profit, "total_profit_abs": profit,
            "liquidation_price": rate * (1 + 0.45) if short else rate * (1 - 0.45), "orders": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"u:p").decode():
            self.send_response(401)
            self.end_headers()
            return
        b = BOTS[self.server.coin]
        body = {"/show_config": b["conf"], "/health": {"last_process_ts": int(time.time())}, "/balance": {"total_bot": 10000.0},
                "/status": b["status"], "/trades": {"trades": b["trades"]}}.get(self.path.split("?")[0].replace("/api/v1", ""))
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


for coin, strat in STRATS.items():
    BOTS[coin] = {"conf": {"dry_run": True, "strategy": strat, "state": "running"}, "status": [], "trades": []}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.coin = coin
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ[f"EA_ENGINE_{coin.upper()}_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
# all three coins on perpetuals, tradable
ea_desk._save(ea_desk.FILES["config"], {"coins": {c: {"market": "perp", "pair": f"{c.upper()}/USDT:USDT", "strategy": s,
                                                       "tradable": True} for c, s in STRATS.items()}})

RESULTS: list[bool] = []


def ok(cond, name, info="") -> None:
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))


def act(coin):
    return ea_desk.signals()["coins"][coin]


# 1. short entry: margin 2000 at 2x = notional 4000 = alloc 0.4 of the bot's 10000
BOTS["sol"]["status"] = [trade("SOL/USDT:USDT", 150.0, 160.0, 2000.0, lev=2.0)]
i = act("sol")
exp_qty = 0.4 * 1000 / 149.0
ok(i["action"] == "OPEN" and i["side"] == "short" and i["market"] == "perp", "引擎做空 → OPEN short（perp）", i.get("why"))
ok(abs(i["qty"] - exp_qty) < 1e-9, "數量 = 名目 alloc × 資金 / 價格（槓桿不放大部位）", (i["qty"], exp_qty))
ok(i["leverage"] == 2.0 and i["margin_mode"] == "isolated" and abs(i["margin_usdt"] - exp_qty * 149 / 2) < 1e-3,
   "逐倉、槓桿 2x、保證金 = 名目 / 2", i)
ok(i["risk"]["risk_usdt"] > 0 and i["risk"]["risk_pct_of_capital"] <= 10.0, "空單風險 = 數量 × (停損 − 價格)", i["risk"])
ok("做空" in i["why"] and "逐倉" in i["why"], "指令文字說明做空與逐倉", i["why"])
ok("min_entry_price" in i and abs(i["min_entry_price"] - 147.0) < 1e-9, "空單追價下限 = 進場價 × (1 − 2%)", i)

# 2. chase limit and stop for shorts
PRICES["SOL/USDT:USDT"] = 146.0
ok(act("sol")["action"] == "MISSED", "價格跌太多（追空） → MISSED")
PRICES["SOL/USDT:USDT"] = 161.0
ok(act("sol")["action"] == "MISSED", "價格已在空單停損之上 → MISSED")
PRICES["SOL/USDT:USDT"] = 149.0
c = ea_desk.check("sol", price=149.0, qty=exp_qty * 1.5)
ok(not c["approved"] and any("超過上限" in r for r in c["reasons"]), "risk_check 擋空單超量", c["reasons"])
c = ea_desk.check("sol", price=149.0, qty=exp_qty)
ok(c["approved"] and c["side"] == "short", "risk_check 通過空單", c["reasons"])

# 3. record OPEN short -> HOLD; stop moves only down
r = ea_desk.record("OPEN", coin="sol", position_id=i["position_id"], qty=exp_qty, price=149.0, fee_usdt=0.1)
ok(r["ok"] and r["side"] == "short" and r["leverage"] == 2.0, "record OPEN short", r)
ok(act("sol")["action"] == "HOLD", "空單部位一致 → HOLD")
BOTS["sol"]["status"][0]["stop_loss_abs"] = 159.5
ok(act("sol")["action"] == "HOLD", "空單停損下移 < 0.5% 不動")
BOTS["sol"]["status"][0]["stop_loss_abs"] = 155.0
i2 = act("sol")
ok(i2["action"] == "MOVE_STOP" and i2["stop_price"] == 155.0 and "下移" in i2["why"], "空單停損下移 → MOVE_STOP", i2.get("why"))
ok(not ea_desk.record("STOP", coin="sol", stop_price=161.0)["ok"], "空單停損不能往上移")
ok(ea_desk.record("STOP", coin="sol", stop_price=155.0)["ok"], "record STOP（空單往下）")

# 4. price through the short stop -> CLOSE_NOW; PnL sign and funding
PRICES["SOL/USDT:USDT"] = 155.5
ok(act("sol")["action"] == "CLOSE_NOW", "價格漲過空單停損 → CLOSE_NOW")
r = ea_desk.record("CLOSE", coin="sol", price=155.0, fee_usdt=0.1, funding_usdt=0.8, reason="stop")
exp = -exp_qty * (155.0 - 149.0) - 0.1 - 0.1 + 0.8
ok(r["ok"] and abs(r["realized_pnl_usdt"] - round(exp, 4)) < 1e-6, "空單平倉損益（含資金費）", (r, exp))
PRICES["SOL/USDT:USDT"] = 149.0
ok(act("sol")["action"] == "MISSED", "同一筆已平倉 → MISSED")

# 5. long on perps, engine exit -> CLOSE; long PnL sign
BOTS["btc"]["status"] = [trade("BTC/USDT:USDT", 99500.0, 80000.0, 1500.0, lev=1.0, short=False, tid=3)]
i = act("btc")
ok(i["action"] == "OPEN" and i["side"] == "long" and "做多" in i["why"], "合約做多 → OPEN long", i.get("why"))
ea_desk.check("btc", price=100000.0, qty=i["qty"])
ea_desk.record("OPEN", coin="btc", position_id=i["position_id"], qty=i["qty"], price=100000.0)
closed = dict(BOTS["btc"]["status"][0], is_open=False, close_timestamp=int(time.time() * 1000), close_rate=104000.0,
              close_date="2026-11-17 00:00:00", exit_reason="trend_off")
BOTS["btc"]["status"], BOTS["btc"]["trades"] = [], [closed]
ok(act("btc")["action"] == "CLOSE", "引擎多單出場 → CLOSE")
r = ea_desk.record("CLOSE", coin="btc", price=104000.0, funding_usdt=-1.5)
ok(r["ok"] and abs(r["realized_pnl_usdt"] - round(i["qty"] * 4000.0 - 1.5, 4)) < 1e-6, "多單平倉損益扣資金費", r)

# 6. engine/AI side mismatch warns; spot coin refuses a short
BOTS["eth"]["status"] = [trade("ETH/USDT:USDT", 3000.0, 3200.0, 1000.0, tid=5)]
r = ea_desk.record("OPEN", coin="eth", qty=0.1, price=3000.0, side="long")
ok(r["ok"] and any("方向" in w for w in r["warnings"]), "方向與引擎不同會警告", r)
ea_desk._save(ea_desk.FILES["config"], {"coins": {"sol": {"market": "spot", "pair": "SOL/USDT", "strategy": "SOLFuturesEA",
                                                          "tradable": True}}})
r = ea_desk.record("OPEN", coin="sol", position_id="EA-SOL-99-x", qty=1, price=149.0, stop_price=160.0, side="short")
ok(not r["ok"] and "現貨" in r["error"], "現貨 EA 不能做空", r)

# 7. ledger columns
rows = ea_desk.rows()
ok(all(r.get("side") in ("long", "short") and r.get("market") for r in rows), "帳本記錄 side 與 market", rows[:1])

print(f"\n{sum(RESULTS)}/{len(RESULTS)} 通過（EA_HOME={TMP}）")
sys.exit(0 if all(RESULTS) else 1)
