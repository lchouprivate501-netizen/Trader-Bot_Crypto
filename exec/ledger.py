"""帳本 state/ledger.csv（沿用 Trader 既有欄位）與權益 state/equity.jsonl。"""
from __future__ import annotations
import csv, json
from datetime import datetime, timezone
from company.paths import STATE

LEDGER = STATE / "ledger.csv"
EQUITY = STATE / "equity.jsonl"
FIELDS = ["fill_id", "ts_utc", "mode", "position_id", "signal_id", "pair", "side", "action", "qty", "price", "leverage",
          "fee_usdt", "stop_price", "realized_pnl_usdt", "reason", "note"]


def rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    with LEDGER.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append(row: dict) -> dict:
    new = not LEDGER.exists()
    r = {k: row.get(k, "") for k in FIELDS}
    r["ts_utc"] = r["ts_utc"] or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(r)
    return r


def open_positions() -> list[dict]:
    pos = {}
    for r in rows():
        a = r["action"].upper()
        if a.startswith("OPEN"):
            pos[r["position_id"]] = r
        elif a.startswith("CLOSE") and r["position_id"] in pos:
            pos.pop(r["position_id"])
    return list(pos.values())


def closes() -> list[dict]:
    return [r for r in rows() if r["action"].upper().startswith("CLOSE")]


def record_equity(equity: float, mode: str, source: str) -> dict:
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "equity_usdt": float(equity), "mode": mode, "source": source}
    with EQUITY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def equity_history() -> list[dict]:
    if not EQUITY.exists():
        return []
    return [json.loads(l) for l in EQUITY.read_text().splitlines() if l.strip()]
