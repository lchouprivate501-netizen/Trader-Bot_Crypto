#!/usr/bin/env python3
"""In-sample grid search of grid parameters (FreqAI predictions must already be cached).

Discipline (same as the repo's R&D rules):
* Run the full walk-forward backtest once first, so every FreqAI window is trained and its
  predictions are cached under user_data/models/<identifier>/.
* Tune ONLY on the in-sample timerange. Its end must sit on a FreqAI window boundary
  (start + k * backtest_period_days), otherwise the last window is retrained and the cache
  is overwritten. Default: 20210601-20241212 (43 windows of 30 days).
* Pick a robust plateau, not the single best cell, then run the out-of-sample segment once.

Example:
  python tune.py --coin btc --grid '{"step_mult":[2,2.5,3],"core_frac":[0.2,0.3,0.5]}'
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
from grid_report import build  # noqa: E402

FEES = {"btc": 0.001, "eth": 0.001, "sol": 0.001}


def run_one(args: tuple) -> dict:
    coin, params, timerange, detail, userdir, py, offline = args
    with tempfile.TemporaryDirectory() as tmp:
        override = {
            "grid_params": params,
            "freqai": {"model_training_parameters": {"n_jobs": 1}},
        }
        if detail:
            override["timeframe_detail"] = detail
        ov = Path(tmp) / "override.json"
        ov.write_text(json.dumps(override))
        out = Path(tmp) / "results"
        out.mkdir()
        # ft_offline.py always applies the backtest-only speed patch; offline also swaps in
        # the static market list
        env = {**os.environ, "FT_OFFLINE": "1" if offline else "0", "FT_FAST": "1"}
        cmd = [py, str(HERE / "ft_offline.py"),
            "backtesting",
            "-c", str(SKILL / "user_data/configs" / f"config_{coin}.json"),
            "-c", str(ov),
            "--userdir", userdir,
            "--strategy-path", str(SKILL / "user_data/strategies"),
            "--freqaimodel-path", str(SKILL / "user_data/freqaimodels"),
            "--timerange", timerange,
            "--fee", str(FEES[coin]),
            "--cache", "none",
            "--backtest-directory", str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        zips = list(out.glob("*.zip"))
        if proc.returncode != 0 or not zips:
            return {"params": params, "error": proc.stderr[-2000:] or proc.stdout[-2000:]}
        rep = build(zips[0], None)
        if "Starting training" in proc.stdout + proc.stderr:
            rep["warning"] = "a FreqAI window was retrained - check the timerange alignment"
        return {"params": params, **rep["full"]["strategy"], "orders": rep["full"]["orders"]}


def check_alignment(coin: str, timerange: str) -> None:
    """Parallel runs must not retrain (and overwrite) a cached FreqAI window."""
    from datetime import datetime

    cfg = json.loads((SKILL / "user_data/configs" / f"config_{coin}.json").read_text())
    period = int(cfg["freqai"]["backtest_period_days"])
    start, end = (datetime.strptime(x, "%Y%m%d") for x in timerange.split("-"))
    days = (end - start).days
    if days % period:
        k = days // period
        ok = [(start.toordinal() + n * period) for n in (k, k + 1)]
        hint = " or ".join(datetime.fromordinal(o).strftime("%Y%m%d") for o in ok)
        sys.exit(
            f"timerange {timerange} is {days} days, not a multiple of backtest_period_days="
            f"{period}: the last FreqAI window would be retrained by every parallel run and "
            f"its cached predictions overwritten. End the range on {hint}."
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coin", required=True, choices=sorted(FEES))
    ap.add_argument("--grid", required=True, help="JSON dict: param -> list of values")
    ap.add_argument("--fixed", default="{}", help="JSON dict of params held fixed")
    ap.add_argument("--timerange", default="20210601-20241212")
    ap.add_argument("--detail", default="5m", help="timeframe_detail (5m: 15m undercounts grid fills)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--userdir", default=os.environ.get("FT_HOME", "user_data"))
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--offline", action="store_true", help="use ft_offline.py (no exchange API)")
    ap.add_argument("--out", help="write the leaderboard as JSON")
    args = ap.parse_args()

    check_alignment(args.coin, args.timerange)
    grid = json.loads(args.grid)
    fixed = json.loads(args.fixed)
    keys = list(grid)
    combos = [{**fixed, **dict(zip(keys, vals, strict=True))} for vals in itertools.product(*grid.values())]
    jobs = [(args.coin, c, args.timerange, args.detail, args.userdir, args.python, args.offline) for c in combos]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(run_one, jobs))

    ok = [r for r in rows if "error" not in r]
    ok.sort(key=lambda r: (r.get("calmar") or -9), reverse=True)
    print(f"{'params':60s} {'ret%':>8s} {'cagr%':>7s} {'mdd%':>6s} {'calmar':>6s} {'sharpe':>6s} buys/sells")
    for r in ok:
        o = r["orders"]
        print(
            f"{json.dumps({k: r['params'][k] for k in keys}):60s} {r['total_return_pct']:8.1f} "
            f"{r['cagr_pct']:7.1f} {r['max_drawdown_pct']:6.1f} {str(r['calmar']):>6s} "
            f"{r['sharpe_daily']:6.2f} {o['grid_buys']}/{o['grid_sells']}"
        )
    for r in rows:
        if "error" in r:
            print("ERROR", r["params"], r["error"][-500:], file=sys.stderr)
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    main()
