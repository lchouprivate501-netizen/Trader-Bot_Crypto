"""Run official skill scripts; do not reimplement their decision logic."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from pionex_trading_skills import paths


def run_python(script: Path, args: list[str], env: dict[str, str] | None = None, timeout: int = 180) -> dict[str, Any]:
    if not script.exists():
        return {"ok": False, "error": f"script not found: {script}", "stdout": "", "stderr": ""}
    cmd = [sys.executable, str(script), *args]
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(script.parent),
            env=merged,
        )
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "error": f"timeout: {exc}", "stdout": "", "stderr": ""}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "cmd": cmd,
    }


def crypto_regime_analyzer(output_dir: Path, top_n: int = 20, cache_dir: Path | None = None) -> dict[str, Any]:
    script = paths.tradermonty() / "skills/crypto-regime-analyzer/scripts/crypto_regime_analyzer.py"
    output_dir.mkdir(parents=True, exist_ok=True)
    args = ["--output-dir", str(output_dir), "--top-n", str(top_n)]
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        args += ["--cache-dir", str(cache_dir)]
    result = run_python(script, args, timeout=300)
    json_path = output_dir / "crypto_regime.json"
    if json_path.exists():
        try:
            result["report"] = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result["report_error"] = str(exc)
    return result


def fetch_usd_tier1_calendar(limit: int = 50) -> dict[str, Any]:
    script = paths.tradermonty() / "skills/fxmacrodata-calendar/scripts/fetch_calendar.py"
    # Do not pass a paid key. USD Tier 1 is documented as usable without one.
    env = {k: v for k, v in os.environ.items() if k != "FMP_API_KEY"}
    env.pop("FXMACRODATA_API_KEY", None)
    result = run_python(script, ["--currency", "usd", "--min-tier", "1", "--limit", str(limit)], env=env)
    if result["ok"]:
        try:
            result["calendar"] = json.loads(result["stdout"])
        except json.JSONDecodeError as exc:
            result["ok"] = False
            result["error"] = f"calendar json parse failed: {exc}"
    else:
        result["status"] = "unconfirmed"
        result["error"] = result.get("error") or result.get("stderr") or "fetch failed"
    return result


def check_circuit_breaker(
    state_dir: Path,
    account_size: float,
    output_dir: Path,
    as_of: str | None = None,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    script = paths.tradermonty() / "skills/drawdown-circuit-breaker/scripts/check_circuit_breaker.py"
    output_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "--state-dir",
        str(state_dir),
        "--account-size",
        str(account_size),
        "--output-dir",
        str(output_dir),
        "--json-only",
    ]
    if as_of:
        args += ["--as-of", as_of]
    if extra_args:
        args += extra_args
    result = run_python(script, args)
    reports = sorted(output_dir.glob("circuit_breaker_decision_*.json"))
    if reports:
        result["report"] = json.loads(reports[-1].read_text(encoding="utf-8"))
        result["report_path"] = str(reports[-1])
    return result


def check_pre_trade_discipline(answers_file: Path, output_dir: Path, extra_args: list[str] | None = None) -> dict[str, Any]:
    script = paths.tradermonty() / "skills/pre-trade-discipline-gate/scripts/check_pre_trade_discipline.py"
    output_dir.mkdir(parents=True, exist_ok=True)
    args = ["--answers-file", str(answers_file), "--output-dir", str(output_dir), "--revenge-window-hours", "24"]
    if extra_args:
        args += extra_args
    result = run_python(script, args)
    reports = sorted(output_dir.glob("pre_trade_discipline_decision_*.json"))
    if reports:
        result["report"] = json.loads(reports[-1].read_text(encoding="utf-8"))
        result["report_path"] = str(reports[-1])
    return result


def signal_postmortem_analyze(postmortems_dir: Path, output_dir: Path) -> dict[str, Any]:
    script = paths.tradermonty() / "skills/signal-postmortem/scripts/postmortem_analyzer.py"
    output_dir.mkdir(parents=True, exist_ok=True)
    return run_python(
        script,
        ["--postmortems-dir", str(postmortems_dir), "--output-dir", str(output_dir), "--summary"],
    )
