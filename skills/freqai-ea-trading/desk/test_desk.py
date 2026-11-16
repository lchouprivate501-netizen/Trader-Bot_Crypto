#!/usr/bin/env python3
"""EA 交易台整合測試：模擬三個 Freqtrade REST API（BTC/ETH/SOL 引擎），逐一檢查每種指令、風控、帳本與 MCP 伺服器。

    python3 skills/freqai-ea-trading/desk/test_desk.py

不需要網路、Freqtrade 或任何套件；用暫存的 EA_HOME，不會動到真的帳本。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="ea-desk-test-")
os.environ["EA_HOME"] = TMP
os.environ["EA_ENGINE_USER"], os.environ["EA_ENGINE_PASSWORD"] = "u", "p"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ea_desk  # noqa: E402

NOW = time.time()
OPEN_TS = int((NOW - 3 * 3600) * 1000)
BOTS: dict[str, dict] = {}
PRICES = {"BTC/USDT": 100500.0, "ETH/USDT": 3000.0, "SOL/USDT": 150.0}
ea_desk.ref_price = lambda pair: PRICES.get(pair)  # no network in tests


def bot(strategy: str) -> dict:
    return {"conf": {"dry_run": True, "strategy": strategy, "state": "running"},
            "health": {"last_process_ts": int(time.time())}, "balance": {"total_bot": 10000.0},
            "status": [], "trades": []}


def open_trade(pair, rate, stop, stake, tid=7, profit=0.0) -> dict:
    return {"trade_id": tid, "pair": pair, "is_open": True, "open_rate": rate, "amount": stake / rate,
            "stake_amount": stake, "stop_loss_abs": stop, "initial_stop_loss_abs": stop, "open_timestamp": OPEN_TS,
            "open_date": "2026-11-16 01:00:00", "current_rate": rate, "enter_tag": "breakout",
            "profit_abs": profit, "total_profit_abs": profit, "orders": []}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        coin = self.server.coin
        if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"u:p").decode():
            self.send_response(401)
            self.end_headers()
            return
        b = BOTS[coin]
        path = self.path.split("?")[0].replace("/api/v1", "")
        body = {"/show_config": b["conf"], "/health": b["health"], "/balance": b["balance"], "/status": b["status"],
                "/trades": {"trades": b["trades"]}}.get(path)
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


SERVERS = {}
for coin, strat in (("btc", "BTCTrendEA"), ("eth", "ETHRiskOnEA"), ("sol", "SOLMomentumEA")):
    BOTS[coin] = bot(strat)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.coin = coin
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SERVERS[coin] = srv
    os.environ[f"EA_ENGINE_{coin.upper()}_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"

# This suite covers the spot setup (all three coins on their spot EAs, ETH shadow-only), set through the user config.
SPOT = {"coins": {"btc": {"market": "spot", "strategy": "BTCTrendEA", "pair": "BTC/USDT", "tradable": True},
                  "eth": {"market": "spot", "strategy": "ETHRiskOnEA", "pair": "ETH/USDT", "tradable": False},
                  "sol": {"market": "spot", "strategy": "SOLMomentumEA", "pair": "SOL/USDT", "tradable": True}}}
ea_desk._save(ea_desk.FILES["config"], SPOT)

RESULTS: list[tuple[bool, str]] = []


def ok(cond: bool, name: str, info="") -> None:
    RESULTS.append((bool(cond), name))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))


def act(coin: str) -> dict:
    return ea_desk.signals()["coins"][coin]


# 1. everything flat
s = ea_desk.signals()
ok([s["coins"][c]["action"] for c in ("btc", "eth", "sol")] == ["WAIT", "SHADOW", "WAIT"], "空手：BTC/SOL WAIT、ETH SHADOW",
   {c: v["action"] for c, v in s["coins"].items()})
ok(s["ea_mode"] == "PAPER", "預設模式 PAPER")

# 2. BTC engine enters: alloc 0.4 of 10000; stop 20% below
BOTS["btc"]["status"] = [open_trade("BTC/USDT", 100000.0, 80000.0, 4000.0)]
i = act("btc")
exp_qty = 0.4 * 1000 / 100500
ok(i["action"] == "OPEN" and i["execution"] == "PAPER", "引擎進場 → OPEN（PAPER）", i.get("why"))
ok(abs(i["qty"] - exp_qty) < 1e-9 and i["risk"]["limited_by"] == "ea_alloc", "數量 = alloc × 資金 / 價格", i.get("risk"))
ok(i["risk"]["risk_pct_of_capital"] <= 10.0, "單筆風險 ≤ 資金 10%", i.get("risk"))
pid = i["position_id"]
ok(pid.startswith("EA-BTC-7-"), "position_id 對應引擎交易", pid)

# 3. risk check: too big qty, price above chase, ETH shadow
c = ea_desk.check("btc", price=100500, qty=exp_qty * 2)
ok(not c["approved"] and any("超過上限" in r for r in c["reasons"]), "risk_check 擋超量", c["reasons"])
c = ea_desk.check("btc", price=102500)
ok(not c["approved"] and any("追價" in r for r in c["reasons"]), "risk_check 擋追價", c["reasons"])
c = ea_desk.check("btc", price=100500, qty=exp_qty)
ok(c["approved"], "risk_check 通過", c["reasons"])
BOTS["eth"]["status"] = [open_trade("ETH/USDT", 3000.0, 2500.0, 3000.0, tid=3)]
ok(act("eth")["action"] == "SHADOW", "ETH 在場內也只是 SHADOW")
c = ea_desk.check("eth", price=3000)
ok(not c["approved"] and any("影子" in r for r in c["reasons"]), "ETH risk_check 不通過", c["reasons"])

# 4. record OPEN -> HOLD
r = ea_desk.record("OPEN", coin="btc", position_id=pid, qty=exp_qty, price=100500, fee_usdt=0.4)
ok(r["ok"] and r["execution"] == "PAPER" and r["stop_price"] == 80000.0, "record OPEN", r)
ok(not ea_desk.record("OPEN", coin="btc", position_id=pid, qty=1, price=1)["ok"], "同一幣不能重複 OPEN")
ok(act("btc")["action"] == "HOLD", "部位一致 → HOLD")

# 5. trailing stop: small move ignored, bigger move -> MOVE_STOP, never down
BOTS["btc"]["status"][0]["stop_loss_abs"] = 80300.0
ok(act("btc")["action"] == "HOLD", "停損上移 < 0.5% 不動")
BOTS["btc"]["status"][0]["stop_loss_abs"] = 85000.0
i = act("btc")
ok(i["action"] == "MOVE_STOP" and i["stop_price"] == 85000.0, "停損上移 → MOVE_STOP", i.get("why"))
ok(ea_desk.record("STOP", coin="btc", stop_price=85000.0)["ok"], "record STOP")
ok(not ea_desk.record("STOP", coin="btc", stop_price=84000.0)["ok"], "停損不能往下移")
ok(act("btc")["action"] == "HOLD", "移動後 HOLD")

# 6. price through the stop -> CLOSE_NOW
PRICES["BTC/USDT"] = 84900.0
i = act("btc")
ok(i["action"] == "CLOSE_NOW", "跌破停損 → CLOSE_NOW", i.get("why"))
r = ea_desk.record("CLOSE", coin="btc", price=84900.0, fee_usdt=0.34, reason="stop")
exp_pnl = exp_qty * (84900 - 100500) - 0.4 - 0.34
ok(r["ok"] and abs(r["realized_pnl_usdt"] - round(exp_pnl, 4)) < 1e-6, "record CLOSE 損益", r)
ok(act("btc")["action"] == "MISSED", "同一筆已平倉 → MISSED（不重複進場）")

# 7. new engine trade, engine exits by trend -> CLOSE
PRICES["BTC/USDT"] = 101000.0
BOTS["btc"]["status"] = [open_trade("BTC/USDT", 100800.0, 90000.0, 5000.0, tid=8)]
i = act("btc")
ok(i["action"] == "OPEN", "下一筆 → OPEN", i.get("why"))
ea_desk.record("OPEN", coin="btc", position_id=i["position_id"], qty=i["qty"], price=101000.0)
closed = dict(BOTS["btc"]["status"][0], is_open=False, close_timestamp=int(time.time() * 1000), close_rate=99000.0,
              close_date="2026-11-17 05:00:00", exit_reason="trend_off", profit_ratio=-0.018)
BOTS["btc"]["status"], BOTS["btc"]["trades"] = [], [closed]
i = act("btc")
ok(i["action"] == "CLOSE" and i["exit_reason"] == "trend_off", "引擎出場 → CLOSE", i.get("why"))
ok(ea_desk.record("CLOSE", coin="btc", price=99000.0)["ok"], "record CLOSE（趨勢出場）")
ok(act("btc")["action"] == "WAIT", "平倉後 WAIT")

# 8. chase limit
BOTS["sol"]["status"] = [open_trade("SOL/USDT", 140.0, 110.0, 2000.0, tid=2)]
i = act("sol")
ok(i["action"] == "MISSED" and "追價" in i["why"], "價格超過追價上限 → MISSED", i.get("why"))
PRICES["SOL/USDT"] = 141.0
ok(act("sol")["action"] == "OPEN", "回到追價範圍 → OPEN")

# 9. guard HALT and desk HALT block new entries
ea_desk._save(ea_desk.FILES["guard"], {"generated_at": "x", "coins": {"sol": {"status": "HALT", "action": "stop"}}})
i = act("sol")
ok(i["action"] == "BLOCKED" and "守衛" in i["why"], "守衛 HALT → BLOCKED", i.get("why"))
ea_desk.FILES["guard"].unlink()
ea_desk.halt("test")
i = act("sol")
ok(i["action"] == "BLOCKED" and ea_desk.ea_mode() == "HALT", "交易台 HALT → BLOCKED", i.get("why"))

# 10. user-only actions refuse without a terminal
cli = [sys.executable, str(HERE / "ea_desk.py")]
env = dict(os.environ)
p = subprocess.run(cli + ["resume"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
ok(p.returncode != 0 and "拒絕" in p.stdout and ea_desk.ea_mode() == "HALT", "AI 不能解除 HALT", p.stdout)
p = subprocess.run(cli + ["live", "on"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
ok(p.returncode != 0 and not ea_desk.live_switch()["enabled"], "AI 不能開實盤", p.stdout)
ea_desk._save(ea_desk.FILES["halt"], {"halted": False})

# 11. LIVE mode: OPEN without a recent approved check warns
ea_desk._save(ea_desk.FILES["live"], {"enabled": True})
i = act("sol")
ok(i["action"] == "OPEN" and i["execution"] == "LIVE", "LIVE → OPEN（LIVE）", i.get("why"))
r = ea_desk.record("OPEN", coin="sol", position_id="EA-SOL-2-x", qty=i["qty"], price=141.0)
ok(r["ok"] and any("risk_check" in w for w in r["warnings"]), "LIVE 沒做 risk_check 會警告", r)
ea_desk.record("CLOSE", coin="sol", price=141.0)

# 12. engine problems
BOTS["sol"]["conf"]["dry_run"] = False
i = act("sol")
ok(i["action"] == "ENGINE_DOWN" and "dry-run" in i["why"], "引擎不是 dry-run → ENGINE_DOWN", i.get("why"))
BOTS["sol"]["conf"]["dry_run"] = True
BOTS["sol"]["health"]["last_process_ts"] = int(time.time()) - 3600
ok(act("sol")["action"] == "ENGINE_DOWN", "引擎停擺 → ENGINE_DOWN")
BOTS["sol"]["health"]["last_process_ts"] = int(time.time())
BOTS["btc"]["status"] = [open_trade("BTC/USDT", 100800.0, 95000.0, 5000.0, tid=9)]
i = act("btc")
r = ea_desk.check("btc", price=101000.0, qty=i["qty"])
ea_desk.record("OPEN", coin="btc", position_id=i["position_id"], qty=i["qty"], price=101000.0)
SERVERS["btc"].shutdown()
SERVERS["btc"].server_close()
i = act("btc")
ok(i["action"] == "ENGINE_DOWN" and i.get("position"), "引擎斷線且有部位 → ENGINE_DOWN（保留停損）", i.get("why"))
PRICES["BTC/USDT"] = 94000.0
ok(act("btc")["action"] == "CLOSE_NOW", "引擎斷線也會在跌破停損時 CLOSE_NOW")
ea_desk.record("CLOSE", coin="btc", price=94000.0)

# 13. loss limit and minimum order
user_cfg = ea_desk._merge(SPOT, {"coins": {"sol": {"capital_usdt": 100}}})
ea_desk._save(ea_desk.FILES["config"], user_cfg)
BOTS["sol"]["status"] = [open_trade("SOL/USDT", 140.0, 110.0, 500.0, tid=5)]
i = act("sol")
ok(i["action"] == "BLOCKED" and "最小金額" in i["why"], "金額太小 → BLOCKED", i.get("why"))
user_cfg["coins"]["sol"]["capital_usdt"] = 1000
ea_desk._save(ea_desk.FILES["config"], user_cfg)
ea_desk._ledger_append({"execution": "LIVE", "position_id": "EA-SOL-90-x", "coin": "sol", "pair": "SOL/USDT",
                        "action": "OPEN", "qty": 10, "price": 140})
ea_desk._ledger_append({"execution": "LIVE", "position_id": "EA-SOL-90-x", "coin": "sol", "pair": "SOL/USDT",
                        "action": "CLOSE", "qty": 10, "price": 100, "realized_pnl_usdt": -400})
i = act("sol")
ok(i["action"] == "BLOCKED" and "回落" in i["why"], "累計虧損 ≥ 資金 35% → BLOCKED", i.get("why"))

# 14. ledger integrity: duplicate open for one coin -> ERROR
for k in ("A", "B"):
    ea_desk._ledger_append({"execution": "PAPER", "position_id": f"EA-ETH-{k}-x", "coin": "eth", "pair": "ETH/USDT",
                            "action": "OPEN", "qty": 1, "price": 3000, "stop_price": 2500})
ok(act("eth")["action"] == "ERROR", "同一幣兩筆部位 → ERROR")

# 15. MCP server over stdio (same command an AI client runs)
mcp = subprocess.Popen([sys.executable, str(HERE / "mcp_server.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, env=env)
n = 0


def rpc(method, params=None):
    global n
    n += 1
    mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n")
    mcp.stdin.flush()
    return json.loads(mcp.stdout.readline())


init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
ok(init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["serverInfo"]["name"] == "freqai-ea-desk", "MCP initialize")
tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
ok(tools == ["ea_guide", "ea_status", "ea_signals", "ea_risk_check", "ea_record", "ea_halt"], "MCP tools/list", tools)
res = {}
for name, args in (("ea_guide", {}), ("ea_status", {}), ("ea_signals", {}), ("ea_risk_check", {"coin": "sol", "price": 141}),
                   ("ea_record", {"event": "SKIP", "coin": "sol", "reason": "test"}), ("nope", {})):
    res[name] = rpc("tools/call", {"name": name, "arguments": args})["result"]
ok("每一輪" in res["ea_guide"]["content"][0]["text"], "MCP ea_guide 回傳作業手冊")
ok(not res["ea_status"]["isError"] and "engines" in json.loads(res["ea_status"]["content"][0]["text"]), "MCP ea_status")
ok("coins" in json.loads(res["ea_signals"]["content"][0]["text"]), "MCP ea_signals")
ok("approved" in json.loads(res["ea_risk_check"]["content"][0]["text"]), "MCP ea_risk_check")
ok(not res["ea_record"]["isError"], "MCP ea_record SKIP")
ok(res["nope"]["isError"], "MCP 未知工具回 isError")
h = rpc("tools/call", {"name": "ea_halt", "arguments": {"reason": "mcp test"}})["result"]
ok(not h["isError"] and ea_desk.ea_mode() == "HALT", "MCP ea_halt")
ok(rpc("bogus/method").get("error", {}).get("code") == -32601, "MCP 未知方法回 -32601")
mcp.stdin.close()
mcp.wait(timeout=10)

passed = sum(c for c, _ in RESULTS)
print(f"\n{passed}/{len(RESULTS)} 通過（EA_HOME={TMP}）")
sys.exit(0 if passed == len(RESULTS) else 1)
