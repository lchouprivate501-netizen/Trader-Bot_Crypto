from __future__ import annotations

import os
from pathlib import Path

SKILL_DOCS: dict[str, tuple[str, str]] = {
    "crypto-regime-analyzer": ("tradermonty", "skills/crypto-regime-analyzer/SKILL.md"),
    "fxmacrodata-calendar": ("tradermonty", "skills/fxmacrodata-calendar/SKILL.md"),
    "drawdown-circuit-breaker": ("tradermonty", "skills/drawdown-circuit-breaker/SKILL.md"),
    "pre-trade-discipline-gate": ("tradermonty", "skills/pre-trade-discipline-gate/SKILL.md"),
    "signal-postmortem": ("tradermonty", "skills/signal-postmortem/SKILL.md"),
    "regime-detection": ("agiprolabs", "skills/regime-detection/SKILL.md"),
    "risk-management": ("agiprolabs", "skills/risk-management/SKILL.md"),
    "signal-classification": ("agiprolabs", "skills/signal-classification/SKILL.md"),
    "volatility-modeling": ("agiprolabs", "skills/volatility-modeling/SKILL.md"),
    "market-microstructure": ("agiprolabs", "skills/market-microstructure/SKILL.md"),
    "walk-forward-validation": ("agiprolabs", "skills/walk-forward-validation/SKILL.md"),
}


def home() -> Path:
    return Path(os.environ.get("PIONEX_MACD_HOME", Path.home() / "crypto-trading" / "pionex-macd")).expanduser()


def crypto_trading() -> Path:
    return Path(os.environ.get("CRYPTO_TRADING_HOME", Path.home() / "crypto-trading")).expanduser()


def tradermonty() -> Path:
    return Path(
        os.environ.get("PIONEX_SKILLS_TRADERMONTY", crypto_trading() / "repos" / "claude-trading-skills")
    ).expanduser()


def agiprolabs() -> Path:
    return Path(
        os.environ.get(
            "PIONEX_SKILLS_AGIPROLABS", crypto_trading() / "repos" / "agiprolabs-trading-skills"
        )
    ).expanduser()


def userdata() -> Path:
    return home() / "user_data"


def gates_dir() -> Path:
    return userdata() / "gates"


def graph_path() -> Path:
    return Path(os.environ.get("GRAPHIFY_GRAPH", home() / "graphify-out" / "graph.json")).expanduser()


def skill_root(kind: str) -> Path:
    return tradermonty() if kind == "tradermonty" else agiprolabs()
