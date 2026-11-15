"""stdio MCP server「pionex-trading-skills」：Trader 私人交易公司的工具箱。

研發部：rnd_registry / rnd_run_backtest / rnd_report / job_status
執行部：news_danger_windows / market_scan / shortlist / analyze_symbol / live_signals / risk_check / risk_state / journal_write
公司：company_status / mode_get / mode_set
本伺服器不持有交易所金鑰、不下單；下單只由 Trader 在瀏覽器的 Pionex 進行。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

ROOT = Path(os.environ.get("PIONEX_MACD_HOME") or Path(__file__).resolve().parents[2])
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("PIONEX_MACD_HOME", str(ROOT))

mcp = MCPServer("pionex-trading-skills")


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _safe(fn):
    try:
        return _j(fn())
    except Exception as e:  # never crash the server on a tool error
        return _j({"ok": False, "error": f"{e.__class__.__name__}: {e}"})


# ---------------- 公司 ----------------
@mcp.tool()
def company_status() -> str:
    """公司總覽：模式、登記簿（PASSED 策略）、是否符合自動轉實盤、風控狀態、消息面、排程器心跳、最新訊號數。每輪先呼叫這個。"""
    def f():
        from company.paths import EXEC, LOGS, load_json
        from exec import mode, news, risk
        from rnd import registry
        reg = registry.load()["strategies"]
        passed = registry.passed()
        hb = load_json(LOGS / "scheduler_heartbeat.json", {})
        pid_ok = False
        try:
            pid = int((LOGS / "scheduler.pid").read_text().strip()); pid_ok = Path(f"/proc/{pid}").exists()
        except Exception:
            pass
        m = mode.get()
        cyc = load_json(EXEC / "state" / "cycle.json", {})
        sig = load_json(EXEC / "signals" / "latest.json", {})
        return {"mode": m, "strategies": {k: v.get("status") for k, v in reg.items()}, "passed": passed,
                "auto_live_eligible": m == "PAPER" and bool(passed),
                "auto_live_rule": "登記簿有 PASSED 策略且模式為 PAPER → Trader 呼叫 mode_set('LIVE') 並通知 Anna",
                "risk": risk.state(), "news": news.status(), "scheduler": {"alive": pid_ok, "heartbeat": hb},
                "last_cycle": cyc, "signals": {"at": sig.get("at"), "total": len(sig.get("signals", [])), "tradable": sig.get("tradable_count", 0)}}
    return _safe(f)


@mcp.tool()
def mode_get() -> str:
    """讀取目前模式 PAPER / LIVE / HALT。"""
    def f():
        from exec import mode
        return {"mode": mode.get()}
    return _safe(f)


@mcp.tool()
def mode_set(mode: str, reason: str) -> str:
    """切換模式。LIVE 只有在登記簿有 PASSED 策略時才允許；HALT 與 PAPER 隨時允許。切 LIVE 後務必通知 Anna。"""
    def f():
        from exec import mode as m
        return m.set_mode(mode, reason)
    return _safe(f)


# ---------------- 研發部 ----------------
@mcp.tool()
def rnd_registry() -> str:
    """策略登記簿：每個策略的狀態（idea/coded/backtested/optimized/PASSED/REJECTED/LIVE）、參數與證據路徑。"""
    def f():
        from rnd import registry
        from rnd.strategies import ALL
        return {"known_modules": ALL, **registry.load()}
    return _safe(f)


@mcp.tool()
def rnd_run_backtest(strategy: str, trials: int = 60, optimize: bool = True) -> str:
    """背景啟動研發流水線：前 70% 優化（trials ≤ 300）→ nautilus 回測樣本內/樣本外 → 報表 → 更新登記簿。立即回傳 job_id，用 job_status 輪詢。"""
    def f():
        from pionex_trading_skills import jobs
        from rnd.strategies import ALL
        if strategy not in ALL:
            return {"ok": False, "error": f"unknown strategy; known {ALL}"}
        args = ["-m", "rnd.pipeline", strategy, "--trials", str(min(int(trials), 300))]
        if not optimize:
            args.append("--no-opt")
        return jobs.start(f"rnd-{strategy}", args)
    return _safe(f)


@mcp.tool()
def job_status(job_id: str) -> str:
    """查詢背景工作（回測/資料下載）狀態與日誌尾端。"""
    def f():
        from pionex_trading_skills import jobs
        return jobs.status(job_id)
    return _safe(f)


@mcp.tool()
def rnd_report(strategy: str) -> str:
    """讀取策略最新報告（樣本外上線門檻表 PASS/FAIL、各幣種/各月份）。"""
    def f():
        from company.paths import REPORTS, load_json
        md = REPORTS / strategy / "report.md"
        if not md.exists():
            return {"ok": False, "error": "尚無報告，先跑 rnd_run_backtest"}
        js = load_json(REPORTS / strategy / "report.json", {})
        return {"markdown": md.read_text(encoding="utf-8"), "passed": js.get("out_of_sample", {}).get("passed")}
    return _safe(f)


# ---------------- 執行部 ----------------
@mcp.tool()
def news_danger_windows(refresh: bool = False, symbol: str = "") -> str:
    """消息面：目前是否處於危險時段（USD 高影響數據、OKX 公告），以及未來 24h 的危險窗口。來源失敗即封鎖（fail-closed）。"""
    def f():
        from exec import news
        if refresh:
            news.refresh()
        return news.status(symbol or None)
    return _safe(f)


@mcp.tool()
def market_scan(refresh: bool = False) -> str:
    """市場掃描：Pionex 白名單內依 OKX 24h 成交額排序前 10–15 名，附 24h 振幅與 5m ATR%。預設讀排程器最新結果。"""
    def f():
        from company.paths import EXEC, load_json
        from exec import scanner
        return scanner.scan() if refresh else load_json(EXEC / "state" / "scan.json", {"note": "尚未產生"})
    return _safe(f)


@mcp.tool()
def shortlist() -> str:
    """篩選：快要觸發策略的標的（near_score ≥ 0.6）。tradable=false 代表該策略未 PASSED，只能觀察。"""
    def f():
        from exec import signals
        return signals.shortlist()
    return _safe(f)


@mcp.tool()
def analyze_symbol(symbol: str, side: str = "") -> str:
    """分析：純規則多時間框架分析（5m/15m/1h/4h 趨勢、RSI、ATR%、資金費率）。給 side 會回 verdict agree/neutral/disagree。"""
    def f():
        from exec import analysis
        return analysis.analyze(symbol.upper().replace("USDT", "").strip("/-"), side or None)
    return _safe(f)


@mcp.tool()
def live_signals(refresh: bool = False) -> str:
    """即時訊號（最新已收盤 5m K）：entry/sl/tp/size/valid_until。只有 tradable=true（策略 PASSED/LIVE）才可交易。"""
    def f():
        from exec import signals
        return signals.run() if refresh else signals.latest()
    return _safe(f)


@mcp.tool()
def risk_check(trade_json: str) -> str:
    """風控：檢查提議交易 {"symbol","side":"long|short","entry","sl","tp","qty"?,"leverage":2,"margin_mode":"isolated"}。回傳 approved、最大數量與原因。下單前必呼叫。"""
    def f():
        from exec import risk
        return risk.check(json.loads(trade_json))
    return _safe(f)


@mcp.tool()
def risk_state() -> str:
    """風控狀態：權益、回撤、今日虧損、連虧、持倉數、是否禁止新單與硬性上限。"""
    def f():
        from exec import risk
        return risk.state()
    return _safe(f)


@mcp.tool()
def journal_write(kind: str, data_json: str) -> str:
    """交易紀錄。kind=fill（成交，欄位 position_id,pair,side,action=OPEN_LONG|OPEN_SHORT|CLOSE_LONG|CLOSE_SHORT,qty,price,leverage,fee_usdt,stop_price,realized_pnl_usdt,signal_id,reason）
    | equity（{"equity_usdt":...} 來自 Pionex 頁面）| note（決策）| skip（放棄訊號原因）。"""
    def f():
        from exec import journal
        return journal.write(kind, json.loads(data_json))
    return _safe(f)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
