#!/usr/bin/env python3
"""Integration test for `ea_guard.py live` against a mock Freqtrade REST API.

Three mock bots on one local server:
  btc  healthy: equity at its high, open trade with an exchange stop order
  eth  drawdown: equity falls 40% below its high-water mark -> HALT, guard must POST /stopentry
  sol  infra: open trade without an exchange stop order -> ALERT, no /stopentry

Run: python test_guard_live.py   (exits non-zero on failure)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOW = time.time()
STATE = {"eth_equity": 10_000.0, "stopentry": []}


def trade(pair: str, with_stop: bool) -> dict:
    orders = [{"ft_order_side": "buy", "is_open": False}]
    if with_stop:
        orders.append({"ft_order_side": "stoploss", "is_open": True})
    return {"pair": pair, "orders": orders, "stoploss_last_update_timestamp": int(NOW * 1000)}


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        bot, _, path = self.path.lstrip("/").partition("/")
        path = "/" + path.split("?")[0]
        if path == "/api/v1/ping":
            return self._send({"status": "pong"})
        if path == "/api/v1/health":
            return self._send({"last_process_ts": int(time.time()) - 60})
        if path == "/api/v1/balance":
            total = {"btc": 10_000.0, "eth": STATE["eth_equity"], "sol": 10_000.0}[bot]
            return self._send({"total": total, "total_bot": total})
        if path == "/api/v1/status":
            return self._send({"btc": [trade("BTC/USDT", True)], "eth": [], "sol": [trade("SOL/USDT", False)]}[bot])
        if path == "/api/v1/trades":
            closed = [{"is_open": False, "close_timestamp": i, "profit_abs": p} for i, p in enumerate([120.0, -40.0, 300.0])]
            return self._send({"trades": closed})
        return self._send({"detail": "not found"}, 404)

    def do_POST(self):
        bot, _, path = self.path.lstrip("/").partition("/")
        if path == "api/v1/stopentry":
            STATE["stopentry"].append(bot)
            return self._send({"status": "No more entries will occur from now. Run /reload_config to reset."})
        return self._send({"detail": "not found"}, 404)


def run_guard(port: int, state: Path, out: Path) -> int:
    env = {**os.environ,
           "EA_GUARD_BOTS": f"btc=http://127.0.0.1:{port}/btc,eth=http://127.0.0.1:{port}/eth,sol=http://127.0.0.1:{port}/sol",
           "EA_GUARD_API_USER": "u", "EA_GUARD_API_PASSWORD": "p"}
    return subprocess.run([sys.executable, str(HERE / "ea_guard.py"), "live", "--act", "--state", str(state),
                           "--json", str(out)], env=env, capture_output=True, text=True).returncode


def main() -> None:
    srv = HTTPServer(("127.0.0.1", 0), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    with tempfile.TemporaryDirectory() as tmp:
        state, out = Path(tmp) / "state.json", Path(tmp) / "report.json"
        code1 = run_guard(port, state, out)              # first pass: records high-water marks
        STATE["eth_equity"] = 6_000.0                     # ETH bot loses 40%
        code2 = run_guard(port, state, out)
        rep = json.loads(out.read_text())["coins"]
        code3 = run_guard(port, state, out)              # third pass: must not send /stopentry again
    srv.shutdown()
    checks = {
        "pass 1 exit code is ALERT (sol has no stop order)": code1 == 2,
        "btc HEALTHY": rep["btc"]["status"] == "HEALTHY",
        "eth HALT on 40% drawdown": rep["eth"]["status"] == "HALT",
        "sol ALERT for missing exchange stop": rep["sol"]["status"] == "ALERT",
        "pass 2 exit code 3 (HALT)": code2 == 3,
        "/stopentry sent to eth exactly once": STATE["stopentry"] == ["eth"],
        "pass 3 still HALT, no duplicate /stopentry": code3 == 3 and STATE["stopentry"] == ["eth"],
    }
    for name, ok in checks.items():
        print(("PASS " if ok else "FAIL ") + name)
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
