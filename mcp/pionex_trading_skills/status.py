"""Age, status, and freshness of external gate files, plus scheduler liveness."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pionex_trading_skills import paths

LOG_DIR = lambda: paths.userdata() / "logs"  # noqa: E731
PIDFILE = lambda: Path(os.environ.get("PIONEX_SCHEDULER_PID", str(paths.userdata() / "logs" / "gate-scheduler.pid")))
POSTMORTEM = lambda: paths.userdata() / "reports" / "signal_postmortem" / "latest.json"
LASTRUN = lambda: paths.userdata() / "logs" / "gate-scheduler-lastrun.json"

FRESH_AFTER = {
    "circuit_breaker": 15 * 60,
    "event_risk": 8 * 3600,
    "crypto_regime": 30 * 3600,
    "postmortem": 8 * 24 * 3600,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def _age_seconds(ts: datetime | None, mtime: float | None) -> float | None:
    if ts is not None:
        return (_now() - ts).total_seconds()
    if mtime is not None:
        return (_now() - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds()
    return None


def _pid_alive() -> dict[str, Any]:
    pidfile = PIDFILE()
    if not pidfile.exists():
        return {"alive": False, "pid": None, "pidfile": str(pidfile), "reason": "no pidfile"}
    try:
        pid = int(pidfile.read_text().strip())
    except ValueError:
        return {"alive": False, "pid": None, "pidfile": str(pidfile), "reason": "malformed pidfile"}
    try:
        os.kill(pid, 0)
        return {"alive": True, "pid": pid, "pidfile": str(pidfile)}
    except OSError:
        return {"alive": False, "pid": pid, "pidfile": str(pidfile), "reason": "pid not running"}


def _file_report(name: str, path: Path, stale_after: int) -> dict[str, Any]:
    info: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "exists": path.is_file(),
        "fresh": False,
        "status": None,
        "age_seconds": None,
        "updated_at": None,
    }
    if not path.is_file():
        info["reason"] = "missing"
        return info
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            info["status"] = raw.get("status") or raw.get("recommendation") or raw.get("zone")
            info["updated_at"] = raw.get("updated_at") or raw.get("as_of") or raw.get("timestamp")
            if name == "circuit_breaker":
                info["recommendation"] = raw.get("recommendation")
            if name == "crypto_regime":
                info["zone"] = raw.get("zone")
            if name == "event_risk":
                info["blocked"] = raw.get("blocked")
    except (OSError, json.JSONDecodeError) as exc:
        info["status"] = "malformed"
        info["reason"] = str(exc)
    ts = _parse_ts(info.get("updated_at"))
    age = _age_seconds(ts, path.stat().st_mtime)
    info["age_seconds"] = None if age is None else round(age, 1)
    info["mtime"] = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    if ts:
        info["updated_at"] = ts.isoformat()
    info["fresh"] = age is not None and age <= stale_after and info.get("status") != "malformed"
    info["stale_after_seconds"] = stale_after
    return info


def collect() -> dict[str, Any]:
    lastrun: dict[str, Any] = {}
    lr = LASTRUN()
    if lr.exists():
        try:
            lastrun = json.loads(lr.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lastrun = {"error": "malformed lastrun file"}
    gates_dir = paths.gates_dir()
    gates = [
        _file_report("circuit_breaker", gates_dir / "circuit_breaker.json", FRESH_AFTER["circuit_breaker"]),
        _file_report("event_risk", gates_dir / "event_risk.json", FRESH_AFTER["event_risk"]),
        _file_report("crypto_regime", gates_dir / "crypto_regime.json", FRESH_AFTER["crypto_regime"]),
        _file_report("postmortem", POSTMORTEM(), FRESH_AFTER["postmortem"]),
    ]
    return {
        "checked_at": _now().isoformat(),
        "scheduler": _pid_alive(),
        "gates": gates,
        "lastrun": lastrun,
        "config_note": "event_risk / circuit_breaker / crypto_regime remain off in config until Anna approves turning them on.",
    }
