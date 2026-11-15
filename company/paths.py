"""Shared paths for the trading company. Root = $PIONEX_MACD_HOME or the repo root."""
from __future__ import annotations
import json, os
from pathlib import Path

ROOT = Path(os.environ.get("PIONEX_MACD_HOME") or Path(__file__).resolve().parents[1])
COMPANY = ROOT / "company"
RND = ROOT / "rnd"
EXEC = ROOT / "exec"
STATE = ROOT / "state"
JOURNAL = ROOT / "journal"
DATA = RND / "data"
REPORTS = RND / "reports"
REGISTRY = RND / "strategies" / "registry.json"
SIGNALS = EXEC / "signals"
LOGS = ROOT / "logs"
JOBS = STATE / "jobs"
for _p in (DATA, REPORTS, SIGNALS, STATE, JOURNAL, LOGS, JOBS):
    _p.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def risk_caps() -> dict:
    return load_json(COMPANY / "risk_caps.json")


def criteria() -> dict:
    return load_json(COMPANY / "live_criteria.json")


def universe() -> dict:
    return load_json(COMPANY / "universe.json")


def pionex_perps() -> list[str]:
    return load_json(COMPANY / "pionex_perps.json")["symbols"]
