"""stdio MCP server: pionex-trading-skills."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from pionex_trading_skills import gatekeeper, graphify_bridge, journal, paths, wrappers

mcp = MCPServer("pionex-trading-skills")


@mcp.tool()
def crypto_regime(top_n: int = 20) -> str:
    """Run tradermonty crypto-regime-analyzer (CoinGecko + Binance funding; funding skipped if blocked). Also writes user_data/gates/crypto_regime.json."""
    return json.dumps(gatekeeper.job_crypto_regime(top_n=top_n), default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def event_calendar(limit: int = 50) -> str:
    """Fetch FXMacroData USD Tier-1 calendar without an API key. On failure status is unconfirmed."""
    return json.dumps(wrappers.fetch_usd_tier1_calendar(limit=limit), default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def job_event_risk(limit: int = 50, minutes_before: int = 30, minutes_after: int = 60) -> str:
    """Write user_data/gates/event_risk.json (fail-closed if the calendar cannot be fetched)."""
    return json.dumps(
        gatekeeper.job_event_risk(limit=limit, minutes_before=minutes_before, minutes_after=minutes_after),
        default=str,
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def circuit_breaker(account_size: float | None = None) -> str:
    """Run tradermonty drawdown-circuit-breaker on freqtrade closed trades and write gates/circuit_breaker.json."""
    return json.dumps(gatekeeper.job_circuit_breaker(account_size=account_size), default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def discipline_check(answers_json: str, output_dir: str | None = None) -> str:
    """Run pre-trade-discipline-gate. answers_json is the official answers file content or a path."""
    dest_dir = Path(output_dir) if output_dir else paths.userdata() / "reports" / "discipline"
    dest_dir.mkdir(parents=True, exist_ok=True)
    raw = answers_json.strip()
    answers_path = Path(raw)
    if not answers_path.exists():
        answers_path = dest_dir / "answers.json"
        # Allow either a path or inline JSON.
        try:
            parsed = json.loads(answers_json)
            answers_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        except json.JSONDecodeError:
            answers_path.write_text(answers_json, encoding="utf-8")
    result = wrappers.check_pre_trade_discipline(answers_path, dest_dir)
    return json.dumps(result, default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def signal_postmortem() -> str:
    """Official signal-postmortem summary if records exist, plus per-gate block-accuracy from the MACD journal."""
    official = None
    pm_dir = paths.userdata() / "reports" / "postmortems"
    if pm_dir.exists() and any(pm_dir.iterdir()):
        official = wrappers.signal_postmortem_analyze(pm_dir, paths.userdata() / "reports")
    accuracy = journal.gate_block_accuracy()
    return json.dumps({"official": official, "gate_block_accuracy": accuracy}, default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def macd_signal(limit_per_pair: int = 3) -> str:
    """Latest MACD raw signals and gate verdicts per pair, from the strategy journal."""
    return json.dumps(journal.latest_signals(limit_per_pair=limit_per_pair), default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def walk_forward_plan() -> str:
    """Rolling walk-forward plan for 15m MACD on ~180 days of OKX USDT perps, from walk-forward-validation skill tables."""
    plan = {
        "timeframe": "15m",
        "bars_per_day": 96,
        "window_type": "rolling",
        "train_days": 30,
        "train_bars": 2880,
        "test_days": 7,
        "test_bars": 672,
        "step_days": 7,
        "embargo_hours": 24,
        "embargo_bars": 96,
        "source": "agiprolabs walk-forward-validation: Intraday (15min-1h) train 14-30d, test 3-7d, embargo 12-24h; crypto prefers rolling windows.",
        "fallback_if_oos_trades_under_50": {"train_days": 14, "test_days": 3, "step_days": 3},
        "note": "180 天約可得到 ~20 個測試摺。實際區間以已下載的 OKX 歷史為準。",
    }
    return json.dumps(plan, ensure_ascii=False, indent=2)


@mcp.tool()
def query_graph(question: str, mode: str = "bfs", depth: int = 3, token_budget: int = 2000) -> str:
    """Passthrough to graphify query_graph on GRAPHIFY_GRAPH."""
    return graphify_bridge.query_graph(question, mode=mode, depth=depth, token_budget=token_budget)


@mcp.tool()
def get_node(label: str) -> str:
    """Passthrough to graphify get_node."""
    return graphify_bridge.get_node(label)


@mcp.tool()
def get_neighbors(label: str, relation_filter: str = "", token_budget: int = 2000) -> str:
    """Passthrough to graphify get_neighbors."""
    return graphify_bridge.get_neighbors(label, relation_filter=relation_filter, token_budget=token_budget)


@mcp.tool()
def graph_stats() -> str:
    """Passthrough to graphify graph_stats."""
    return graphify_bridge.graph_stats()


@mcp.tool()
def skill_docs(name: str) -> str:
    """Return the SKILL.md text of one of the 11 installed skills. Pass the skill directory name."""
    key = name.strip()
    if key not in paths.SKILL_DOCS:
        return json.dumps(
            {"error": "unknown skill", "available": sorted(paths.SKILL_DOCS)},
            ensure_ascii=False,
            indent=2,
        )
    kind, rel = paths.SKILL_DOCS[key]
    path = paths.skill_root(kind) / rel
    if not path.exists():
        return f"SKILL.md not found: {path}"
    return f"# {key}\n# source: {path}\n\n" + path.read_text(encoding="utf-8")


@mcp.tool()
def job_crypto_regime(top_n: int = 20) -> str:
    """Alias for writing the crypto_regime gate file (cron-friendly)."""
    return crypto_regime(top_n=top_n)


@mcp.tool()
def job_circuit_breaker(account_size: float | None = None) -> str:
    """Alias for circuit_breaker job."""
    return circuit_breaker(account_size=account_size)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
