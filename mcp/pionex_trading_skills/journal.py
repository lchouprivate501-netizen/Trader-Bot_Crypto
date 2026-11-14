from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from pionex_trading_skills import paths


def journal_path() -> Path:
    return paths.userdata() / "logs" / "macd_gate_journal.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def latest_signals(limit_per_pair: int = 3) -> dict[str, Any]:
    rows = [r for r in read_jsonl(journal_path()) if r.get("event") in {"raw_signal", "entry_decision"}]
    by_pair: dict[str, list] = defaultdict(list)
    for row in reversed(rows):
        pair = row.get("pair") or "?"
        if len(by_pair[pair]) < limit_per_pair:
            by_pair[pair].append(row)
    return {"journal": str(journal_path()), "exists": journal_path().exists(), "latest": by_pair}


def _load_pair_closes(pair: str) -> pd.Series | None:
    # freqtrade okx futures filenames look like BTC_USDT_USDT-15m.feather / .json
    slug = pair.replace("/", "_").replace(":", "_")
    base = paths.userdata() / "data" / "okx"
    candidates = list(base.rglob(f"{slug}-15m.*")) + list(base.rglob(f"*{slug}*15m*"))
    for path in candidates:
        try:
            if path.suffix == ".feather":
                df = pd.read_feather(path)
            elif path.suffix in {".json", ".json.gz"}:
                df = pd.read_json(path)
            else:
                continue
            if "date" in df.columns and "close" in df.columns:
                s = df.set_index(pd.to_datetime(df["date"]))["close"].sort_index()
                return s
        except Exception:
            continue
    return None


def gate_block_accuracy() -> dict[str, Any]:
    """For each blocked raw signal, check whether the skipped direction lost after the signal.

    Uses next 16 bars (~4h) close-to-close when OHLC data is available.
    A block is 'correct' if a blocked long would have had a negative forward return
    (or a blocked short a positive one).
    """
    rows = [r for r in read_jsonl(journal_path()) if r.get("event") == "raw_signal"]
    gates = [
        "gate_regime_ok",
        "gate_vol_ok",
        "gate_pressure_long_ok",
        "gate_pressure_short_ok",
        "gate_structure_long_ok",
        "gate_structure_short_ok",
        "gate_btc_long_ok",
        "gate_btc_short_ok",
    ]
    stats: dict[str, dict[str, int]] = {g: {"blocked": 0, "correct": 0, "incorrect": 0, "unknown": 0} for g in gates}
    cache: dict[str, pd.Series | None] = {}
    for row in rows:
        if row.get("passed_vector_gates"):
            continue
        pair = row.get("pair")
        side = row.get("side")
        ts = row.get("date")
        if pair not in cache:
            cache[pair] = _load_pair_closes(pair)
        series = cache[pair]
        fwd = None
        if series is not None and ts:
            try:
                t = pd.Timestamp(ts)
                after = series[series.index > t]
                if len(after) >= 16:
                    fwd = float(after.iloc[15] / series.asof(t) - 1)
            except Exception:
                fwd = None
        for g in gates:
            if g.endswith("_long_ok") and side != "long":
                continue
            if g.endswith("_short_ok") and side != "short":
                continue
            # Generic gates apply to both sides.
            val = row.get(g)
            if val is True or val is None:
                continue
            if val is False:
                stats[g]["blocked"] += 1
                if fwd is None:
                    stats[g]["unknown"] += 1
                else:
                    good = (side == "long" and fwd < 0) or (side == "short" and fwd > 0)
                    stats[g]["correct" if good else "incorrect"] += 1
    for g, s in stats.items():
        denom = s["correct"] + s["incorrect"]
        s["accuracy"] = (s["correct"] / denom) if denom else None
    return {
        "signals": len(rows),
        "blocked_signals": sum(1 for r in rows if not r.get("passed_vector_gates")),
        "forward_horizon_bars": 16,
        "per_gate": stats,
        "note": "正確＝擋住後該方向 16 根內報酬不利。資料不足時列 unknown。",
    }
