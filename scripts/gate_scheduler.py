#!/usr/bin/env python3
"""UTC gatekeeper loop for hosts without systemd/cron.

Reads scripts/gate_schedule.cron and runs `pionex-gatekeeper <job>`
in the stack working directory. Writes a pidfile and a log.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("PIONEX_MACD_HOME", Path(__file__).resolve().parents[1])).expanduser()
SCHEDULE = Path(os.environ.get("PIONEX_GATE_SCHEDULE", ROOT / "scripts" / "gate_schedule.cron"))
LOG_DIR = ROOT / "user_data" / "logs"
PIDFILE = Path(os.environ.get("PIONEX_SCHEDULER_PID", LOG_DIR / "gate-scheduler.pid"))
LOGFILE = Path(os.environ.get("PIONEX_SCHEDULER_LOG", LOG_DIR / "gate-scheduler.log"))
LASTRUN = LOG_DIR / "gate-scheduler-lastrun.json"
VENV_BIN = Path(
    os.environ.get(
        "PIONEX_MCP_BIN",
        Path(os.environ.get("CRYPTO_TRADING_HOME", ROOT.parent)) / "venvs" / "pionex-trading-skills" / "bin",
    )
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(second=0, microsecond=0)


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        if os.path.samefile("/proc/self/fd/1", LOGFILE):
            return
    except OSError:
        pass
    with LOGFILE.open("a", encoding="utf-8") as fh:
        fh.write(line)


def parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if part.startswith("*/"):
            step = int(part[2:])
            values.update(range(minimum, maximum + 1, step))
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            values.update(range(int(a), int(b) + 1))
            continue
        values.add(int(part))
    return values


def cron_dow_ok(now: datetime, dow: str) -> bool:
    wanted = parse_field(dow, 0, 7)
    iso = now.isoweekday()  # 1-7, Mon-Sun
    cron = 0 if iso == 7 else iso
    return cron in wanted or (iso == 7 and 7 in wanted)


def load_schedule(path: Path) -> list[tuple[str, str, str, str, str, str]]:
    jobs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 6:
            log(f"skip malformed schedule line: {raw}")
            continue
        jobs.append(tuple(parts))  # type: ignore[arg-type]
    return jobs  # (min, hour, day, month, dow, job)


def load_lastrun() -> dict[str, str]:
    if not LASTRUN.exists():
        return {}
    try:
        return json.loads(LASTRUN.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_lastrun(stamp: dict[str, str]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LASTRUN.write_text(json.dumps(stamp, indent=2) + "\n", encoding="utf-8")


def run_job(name: str) -> int:
    cmd = [str(VENV_BIN / "pionex-gatekeeper"), name]
    env = os.environ.copy()
    env.setdefault("PIONEX_MACD_HOME", str(ROOT))
    env.setdefault("CRYPTO_TRADING_HOME", str(ROOT.parent))
    log(f"start job={name} cwd={ROOT} cmd={' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"fail job={name} error={exc}")
        return 1
    out = (proc.stdout or "").strip().replace("\n", " | ")
    err = (proc.stderr or "").strip().replace("\n", " | ")
    log(f"done job={name} rc={proc.returncode} stdout={out[-1500:]} stderr={err[-800:]}")
    return proc.returncode


def due(now: datetime, minute: str, hour: str, day: str, month: str, dow: str) -> bool:
    return (
        now.minute in parse_field(minute, 0, 59)
        and now.hour in parse_field(hour, 0, 23)
        and now.day in parse_field(day, 1, 31)
        and now.month in parse_field(month, 1, 12)
        and cron_dow_ok(now, dow)
    )


def write_pid() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()) + "\n", encoding="utf-8")


def clear_pid() -> None:
    try:
        if PIDFILE.exists() and PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink()
    except OSError:
        pass


def already_running() -> int | None:
    if not PIDFILE.exists():
        return None
    try:
        pid = int(PIDFILE.read_text().strip())
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    if pid == os.getpid():
        return None
    return pid


def main() -> int:
    if not SCHEDULE.exists():
        print(f"schedule not found: {SCHEDULE}", file=sys.stderr)
        return 2
    other = already_running()
    if other:
        print(f"scheduler already running pid={other}", file=sys.stderr)
        return 0
    write_pid()
    stopping = False

    def _stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log(f"scheduler start pid={os.getpid()} root={ROOT} schedule={SCHEDULE}")
    jobs = load_schedule(SCHEDULE)
    stamps = load_lastrun()
    while not stopping:
        now = utcnow()
        key_time = now.strftime("%Y-%m-%dT%H:%M")
        for minute, hour, day, month, dow, name in jobs:
            stamp_key = f"{name}:{key_time}"
            if due(now, minute, hour, day, month, dow) and stamps.get(name) != key_time:
                rc = run_job(name)
                stamps[name] = key_time
                stamps[f"{name}_rc"] = str(rc)
                stamps[f"{name}_at"] = datetime.now(timezone.utc).isoformat()
                save_lastrun(stamps)
                log(f"marked {stamp_key} rc={rc}")
        # sleep until a bit after the next minute
        delay = 60 - datetime.now(timezone.utc).second
        delay = min(max(delay, 5), 60)
        for _ in range(delay):
            if stopping:
                break
            time.sleep(1)
    log("scheduler stop")
    clear_pid()
    return 0


if __name__ == "__main__":
    sys.exit(main())
