"""Temp-copy tests for exchange_set. Does not touch the live company/exchange.json.
Usage: PIONEX_MACD_HOME must NOT be pre-imported; this script sets a temp home in a subprocess-safe way.
  python scripts/test_exchange_set.py
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _prep(tmp: Path) -> None:
    shutil.copytree(REPO / "company", tmp / "company", ignore=shutil.ignore_patterns("__pycache__"))
    # do not copy live runtime; give isolated state
    (tmp / "state").mkdir()
    (tmp / "exec" / "state").mkdir(parents=True)
    (tmp / "logs").mkdir()
    (tmp / "journal").mkdir()
    (tmp / "state" / "mode").write_text("PAPER\n")
    # empty ledger
    fields = ["fill_id", "ts_utc", "mode", "position_id", "signal_id", "pair", "side", "action", "qty", "price", "leverage",
              "fee_usdt", "stop_price", "realized_pnl_usdt", "reason", "note"]
    with (tmp / "state" / "ledger.csv").open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fields).writeheader()


def _import():
    # company.paths.ROOT is fixed at import; this process must start with PIONEX_MACD_HOME already set.
    from company.exchange import set_profile, snapshot, taker_fee, whitelist, active_name, POINTER, path_for
    return set_profile, snapshot, taker_fee, whitelist, active_name, POINTER, path_for


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="exchange-test-"))
    os.environ["PIONEX_MACD_HOME"] = str(tmp)
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    # If company was already imported, abort — this file must be the entry point.
    if "company.paths" in sys.modules or "company.exchange" in sys.modules:
        print("FAIL: company already imported; run this as a fresh process")
        return 1
    _prep(tmp)
    set_profile, snapshot, taker_fee, whitelist, active_name, POINTER, path_for = _import()
    from company.paths import ROOT
    assert ROOT == tmp, f"ROOT={ROOT} tmp={tmp}"
    live_pointer = json.loads((REPO / "company" / "exchange.json").read_text())
    assert live_pointer.get("active") == "pionex", "live active exchange must stay pionex during this test"

    fails = []

    def check(name, cond, detail=""):
        if cond:
            print(f"ok  {name}")
        else:
            print(f"FAIL {name} {detail}")
            fails.append(name)

    snap = snapshot()
    check("default pionex", snap.get("active") == "pionex" and snap.get("ok"), snap)
    check("default taker 5bps", taker_fee() == 0.0005, taker_fee())
    check("whitelist has BTC", "BTC" in whitelist())

    # name switch no-op
    r = set_profile("pionex")
    check("set pionex noop", r.get("ok") and r.get("unchanged"), r)

    fake = {
        "name": "paperx",
        "display_name": "PaperX (test)",
        "web_login_url": "https://example.com/exchange",
        "contract_naming": "{base}USDT perp",
        "whitelist": ["BTC", "ETH"],
        "maker_fee": 0.0001,
        "taker_fee": 0.0004,
        "supports_isolated": True,
        "supports_usdt_margined_perps": True,
        "max_leverage": 20,
        "notes": "fake profile for tests only",
    }
    r = set_profile(json.dumps(fake))
    check("write fake profile", r.get("ok") and r.get("active") == "paperx", r)
    check("fees from fake profile", taker_fee() == 0.0004 and whitelist() == ["BTC", "ETH"], (taker_fee(), whitelist()))
    check("live tree unchanged after write", json.loads((REPO / "company" / "exchange.json").read_text()).get("active") == "pionex")

    bad_key = dict(fake, name="evilx", api_key="SHOULD_NEVER_BE_STORED")
    r = set_profile(json.dumps(bad_key))
    check("reject api_key", (not r.get("ok")) and ("secret" in r.get("error","").lower() or "api_key" in r.get("error","").lower() or "api" in r.get("error","").lower()), r)
    check("evilx not written", not (tmp / "company/exchanges/evilx.json").exists())

    bad_iso = dict(fake, name="crossx", supports_isolated=False)
    r = set_profile(json.dumps(bad_iso))
    check("reject no isolated", r.get("ok") is False and "isolated" in r.get("error", "").lower(), r)

    bad_lev = dict(fake, name="lowx", max_leverage=1)
    r = set_profile(json.dumps(bad_lev))
    check("reject leverage < 2", r.get("ok") is False and "2" in r.get("error", ""), r)

    # LIVE + open position must refuse switch back to pionex
    (tmp / "state" / "mode").write_text("LIVE\n")
    fields = ["fill_id", "ts_utc", "mode", "position_id", "signal_id", "pair", "side", "action", "qty", "price", "leverage",
              "fee_usdt", "stop_price", "realized_pnl_usdt", "reason", "note"]
    with (tmp / "state" / "ledger.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow({k: "" for k in fields} | {
            "fill_id": "t1", "ts_utc": "2026-11-15T00:00:00Z", "mode": "LIVE",
            "position_id": "POS-TEST", "pair": "BTC/USDT", "side": "long",
            "action": "OPEN_LONG", "qty": "0.01", "price": "100000", "leverage": "2",
        })
    r = set_profile("pionex")
    check("refuse switch while LIVE+open", r.get("ok") is False and "LIVE" in r.get("error", ""), r)
    check("still paperx after refuse", active_name() == "paperx", active_name())

    # live repo pointer still pionex
    check(
        "live active still pionex at end",
        json.loads((REPO / "company" / "exchange.json").read_text()).get("active") == "pionex",
    )

    shutil.rmtree(tmp, ignore_errors=True)
    if fails:
        print(f"{len(fails)} failed: {fails}")
        return 1
    print("all exchange_set temp-copy tests passed; live exchange unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
