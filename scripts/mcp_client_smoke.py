#!/usr/bin/env python3
"""Call every pionex-trading-skills MCP tool over stdio and print summaries."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(os.environ.get("PIONEX_MACD_HOME", Path(__file__).resolve().parents[1]))
VENV_PY = Path(os.environ.get("PIONEX_MCP_PYTHON", Path.home() / "crypto-trading/venvs/pionex-trading-skills/bin/python"))


def _preview(text: str, limit: int = 800) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "\n…[truncated]…"


async def main() -> int:
    env = os.environ.copy()
    env.setdefault("PIONEX_MACD_HOME", str(ROOT))
    env.setdefault("CRYPTO_TRADING_HOME", str(ROOT.parent))
    params = StdioServerParameters(command=str(VENV_PY), args=["-m", "pionex_trading_skills"], env=env)
    calls = [
        ("walk_forward_plan", {}),
        ("skill_docs", {"name": "regime-detection"}),
        ("macd_signal", {"limit_per_pair": 1}),
        ("signal_postmortem", {}),
        ("graph_stats", {}),
        ("query_graph", {"question": "MACD gate"}),
        ("get_node", {"label": "MacdGatedFutures"}),
        ("get_neighbors", {"label": "MacdGatedFutures"}),
        ("event_calendar", {"limit": 5}),
        ("job_event_risk", {"limit": 5}),
        ("circuit_breaker", {}),
        ("discipline_check", {
            "answers_json": json.dumps({
                "candidates": [{
                    "symbol": "BTC",
                    "order_intent": "WATCHLIST",
                    "entry_in_written_plan": True,
                    "stop_predefined": True,
                    "size_within_plan": True,
                    "planned_risk_dollars": 0,
                    "actual_risk_dollars": 0,
                    "notes": "smoke",
                }]
            })
        }),
        # crypto_regime hits the network and may be slow; still required.
        ("crypto_regime", {"top_n": 5}),
    ]
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("TOOLS:", ", ".join(sorted(names)))
            missing = {c[0] for c in calls} - set(names)
            if missing:
                print("MISSING TOOLS:", missing)
            for name, args in calls:
                print("\n========", name, "========")
                try:
                    result = await session.call_tool(name, args)
                    texts = []
                    for block in result.content:
                        texts.append(getattr(block, "text", str(block)))
                    print(_preview("\n".join(texts), 1200))
                except Exception as exc:  # noqa: BLE001
                    print("ERROR:", exc)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
