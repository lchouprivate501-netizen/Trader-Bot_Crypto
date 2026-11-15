"""stdio JSON-RPC 煙霧測試：用與連接器相同的指令啟動 MCP，tools/list 後逐一 tools/call。
用法: python scripts/mcp_smoke.py
（rnd_run_backtest 以不存在的策略名測試，不會覆寫任何報告；--with-backtest NAME 會真的重跑並覆寫該策略報告與登記簿）"""
import json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(os.environ.get("CRYPTO_TRADING_HOME", os.path.dirname(ROOT)), "venvs/pionex-trading-skills/bin/python")
CALLS = [
    ("company_status", {}), ("mode_get", {}), ("mode_set", {"mode": "LIVE", "reason": "smoke test: must be refused without PASSED"}),
    ("mode_set", {"mode": "PAPER", "reason": "smoke test"}), ("rnd_registry", {}), ("rnd_report", {"strategy": "vwap_pullback"}),
    ("job_status", {"job_id": "none"}), ("news_danger_windows", {}), ("market_scan", {}), ("shortlist", {}),
    ("analyze_symbol", {"symbol": "BTC", "side": "short"}), ("live_signals", {}),
    ("risk_check", {"trade_json": json.dumps({"symbol": "ETH", "side": "long", "entry": 3000, "sl": 2970, "leverage": 2})}),
    ("risk_state", {}), ("rnd_run_backtest", {"strategy": "__smoke_noop__"}), ("journal_write", {"kind": "note", "data_json": json.dumps({"text": "MCP smoke test"})}),
    ("exchange_get", {}), ("setup_check", {}),
]


def main():
    extra = []
    if "--with-backtest" in sys.argv:
        extra = [("rnd_run_backtest", {"strategy": sys.argv[sys.argv.index("--with-backtest") + 1], "trials": 5})]
    env = dict(os.environ, PIONEX_MACD_HOME=ROOT, CRYPTO_TRADING_HOME=os.path.dirname(ROOT))
    p = subprocess.Popen([PY, "-m", "pionex_trading_skills"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    n = [0]

    def rpc(method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})}
        if not notify:
            n[0] += 1; msg["id"] = n[0]
        p.stdin.write(json.dumps(msg) + "\n"); p.stdin.flush()
        if notify:
            return None
        while True:
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("server exited: " + p.stderr.read()[-2000:])
            r = json.loads(line)
            if r.get("id") == n[0]:
                return r

    t = time.time()
    init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}})
    rpc("notifications/initialized", notify=True)
    tools = rpc("tools/list", {})["result"]["tools"]
    print(f"initialize+list {time.time()-t:.2f}s; server {init['result']['serverInfo']}; {len(tools)} tools: {[x['name'] for x in tools]}")
    ok = True
    for name, args in CALLS + extra:
        t = time.time()
        r = rpc("tools/call", {"name": name, "arguments": args})
        res = r.get("result", {})
        text = res.get("content", [{}])[0].get("text", "") if res else json.dumps(r.get("error"))
        err = res.get("isError") or "error" in r
        ok &= not err
        print(f"{'ERR' if err else 'ok '} {name:22s} {time.time()-t:5.2f}s  {text[:160].replace(chr(10),' ')}")
    p.stdin.close(); p.terminate()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
