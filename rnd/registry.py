"""策略登記簿 rnd/strategies/registry.json：idea/coded/backtested/optimized/PASSED/REJECTED/LIVE。"""
from __future__ import annotations
import fcntl
from datetime import datetime, timezone
from company.paths import REGISTRY, load_json, write_json

STATUSES = ["idea", "coded", "backtested", "optimized", "PASSED", "REJECTED", "LIVE"]


def load() -> dict:
    return load_json(REGISTRY, {"strategies": {}})


def set_status(name: str, status: str, **fields) -> dict:
    assert status in STATUSES, status
    lock = open(REGISTRY.with_suffix(".lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)  # several pipelines may run at once
    try:
        return _set(name, status, **fields)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()


def _set(name: str, status: str, **fields) -> dict:
    reg = load()
    s = reg["strategies"].setdefault(name, {"history": []})
    s.update(fields)
    s["status"] = status
    s["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    s.setdefault("history", []).append({"status": status, "at": s["updated"]})
    write_json(REGISTRY, reg)
    return s


def passed() -> list[str]:
    return [k for k, v in load()["strategies"].items() if v.get("status") in ("PASSED", "LIVE")]
