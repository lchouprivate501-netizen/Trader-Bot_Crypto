"""Write user_data/gates/*.json. Callable as MCP tools and as a CLI for cron."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from pionex_trading_skills import paths
from pionex_trading_skills import wrappers


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write_gate(name: str, payload: dict[str, Any]) -> Path:
    paths.gates_dir().mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("updated_at", _now().isoformat())
    dest = paths.gates_dir() / f"{name}.json"
    dest.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


def job_event_risk(limit: int = 50, minutes_before: int = 30, minutes_after: int = 60) -> dict[str, Any]:
    fetched = wrappers.fetch_usd_tier1_calendar(limit=limit)
    if not fetched.get("ok"):
        payload = {
            "status": "unconfirmed",
            "blocked": True,
            "reason": fetched.get("error") or fetched.get("stderr") or "calendar fetch failed",
            "fail_closed": True,
        }
        path = _write_gate("event_risk", payload)
        payload["path"] = str(path)
        return payload
    calendar = fetched.get("calendar") or {}
    events = calendar.get("events") or []
    now = _now()
    blocking = []
    for ev in events:
        raw = ev.get("release_at") or ev.get("datetime") or ev.get("date") or ev.get("time")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        start = ts - timedelta(minutes=minutes_before)
        end = ts + timedelta(minutes=minutes_after)
        if start <= now <= end:
            blocking.append(ev)
    payload = {
        "status": "ok",
        "blocked": bool(blocking),
        "window": {"minutes_before": minutes_before, "minutes_after": minutes_after},
        "blocking_events": blocking,
        "event_count": len(events),
        "policy_note": "30/60 分鐘視窗是本堆疊的 event_risk 政策，不是日曆技能本文的欄位。",
        "calendar_timezone": calendar.get("timezone"),
    }
    path = _write_gate("event_risk", payload)
    payload["path"] = str(path)
    return payload


def job_crypto_regime(top_n: int = 20) -> dict[str, Any]:
    out = paths.userdata() / "reports" / "crypto_regime"
    cache = paths.userdata() / ".crypto_regime_cache"
    result = wrappers.crypto_regime_analyzer(out, top_n=top_n, cache_dir=cache)
    report = result.get("report") or {}
    composite = report.get("composite") or report
    zone = str(composite.get("zone") or report.get("zone") or "").upper()
    payload = {
        "status": "ok" if result.get("ok") or report else "error",
        "zone": zone or None,
        "score": composite.get("score") or report.get("score"),
        "guidance": composite.get("guidance") or report.get("guidance"),
        "binance_note": "資金費使用 Binance 公開端點；若被封鎖，官方腳本會略過該元件。",
        "allow_long": zone != "RISK_OFF",
        "allow_short": zone != "RISK_ON",
        "policy_note": "RISK_OFF 不開多、RISK_ON 不開空是本策略閘門政策；技能原文聲明不做授權/阻擋。",
        "stdout": (result.get("stdout") or "")[-2000:],
        "stderr": (result.get("stderr") or "")[-2000:],
        "ok": bool(result.get("ok") or report),
    }
    if not payload["ok"]:
        payload["status"] = "error"
    path = _write_gate("crypto_regime", payload)
    payload["path"] = str(path)
    return payload


def _trades_from_sqlite(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT * FROM trades WHERE is_open = 0 OR is_open = '0'"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        con.close()
    return [dict(r) for r in rows]


def _export_theses(trades: list[dict[str, Any]], state_dir: Path) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for i, t in enumerate(trades):
        tid = str(t.get("id") or t.get("trade_id") or f"ft-{i}")
        close_date = t.get("close_date") or t.get("close_date_utc") or t.get("close_dt")
        pnl = t.get("close_profit_abs")
        if pnl is None:
            pnl = t.get("realized_profit") or t.get("profit_abs") or 0
        pair = str(t.get("pair") or t.get("ticker") or "UNKNOWN")
        ticker = pair.split("/")[0]
        thesis = {
            "thesis_id": f"ft-{tid}",
            "ticker": ticker,
            "created_at": str(t.get("open_date") or close_date or _now().isoformat()),
            "updated_at": str(close_date or _now().isoformat()),
            "thesis_type": "macd_gated",
            "status": "CLOSED",
            "status_history": [
                {
                    "status": "CLOSED",
                    "at": str(close_date or _now().isoformat()),
                    "realized_pnl": float(pnl or 0),
                    "reason": str(t.get("exit_reason") or "freqtrade"),
                }
            ],
            "thesis_statement": f"{pair} freqtrade trade {tid}",
            "origin": {"skill": "freqtrade-adapter", "output_file": "trades"},
            "outcome": {"pnl_dollars": float(pnl or 0)},
        }
        (state_dir / f"ft-{tid}.yaml").write_text(yaml.safe_dump(thesis, sort_keys=False), encoding="utf-8")
        count += 1
    return count


def job_circuit_breaker(account_size: float | None = None) -> dict[str, Any]:
    account_size = float(account_size or _wallet_size())
    state_dir = paths.userdata() / "state" / "theses"
    reports = paths.userdata() / "reports" / "circuit_breaker"
    db_candidates = [
        paths.userdata() / "tradesv3.dryrun.sqlite",
        paths.userdata() / "tradesv3.sqlite",
        paths.userdata() / "dryrun.sqlite",
    ]
    trades: list[dict[str, Any]] = []
    used_db = None
    for db in db_candidates:
        trades = _trades_from_sqlite(db)
        if trades:
            used_db = str(db)
            break
    written = _export_theses(trades, state_dir)
    result = wrappers.check_circuit_breaker(state_dir, account_size, reports)
    report = result.get("report") or {}
    payload = {
        "status": "ok" if result.get("ok") else "error",
        "recommendation": report.get("recommendation"),
        "rationale": report.get("rationale"),
        "data_quality": report.get("data_quality"),
        "trades_exported": written,
        "source_db": used_db,
        "stdout": (result.get("stdout") or "")[-2000:],
        "stderr": (result.get("stderr") or "")[-2000:],
        "ok": bool(result.get("ok")),
    }
    if not trades:
        payload["note"] = "尚無已平倉成交（ledger 空）。技能腳本仍會產生建議。"
    path = _write_gate("circuit_breaker", payload)
    payload["path"] = str(path)
    return payload


def _wallet_size() -> float:
    cfg = paths.userdata() / "config.macd.futures.json"
    try:
        return float(json.loads(cfg.read_text()).get("dry_run_wallet") or 1000)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 1000.0


JOBS = {
    "event_risk": job_event_risk,
    "crypto_regime": job_crypto_regime,
    "circuit_breaker": job_circuit_breaker,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write MACD external gate JSON files")
    parser.add_argument("job", choices=[*JOBS, "all"])
    args = parser.parse_args(argv)
    jobs = list(JOBS) if args.job == "all" else [args.job]
    failed = False
    for name in jobs:
        try:
            out = JOBS[name]()
        except Exception as exc:  # noqa: BLE001 - CLI must not crash cron silently
            print(f"{name}: ERROR {exc}", file=sys.stderr)
            failed = True
            continue
        print(json.dumps({"job": name, **{k: v for k, v in out.items() if k != "blocking_events"}}, default=str))
        if out.get("status") not in {"ok", "unconfirmed"} and not out.get("ok", True):
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
