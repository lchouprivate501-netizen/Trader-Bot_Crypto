#!/usr/bin/env python3
"""Where does an EA backtest make and lose its money, and were its exits any good?

Per trade: entry / exit time, exit reason, PnL, holding time, and what the price did 3 and 14 days
after the exit (did a stop sell the low? did a trend exit avoid the drop?). Summaries by year, by
exit reason and by in-sample / out-of-sample segment.

Usage (Freqtrade venv): python exit_analysis.py <result.zip> [--split 2024-12-12] [--json out.json]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mtm_report import load  # noqa: E402


def fwd_return(close: pd.Series, t: pd.Timestamp, price: float, hours: int) -> float | None:
    """Price change from an exit price to the first close at least `hours` later."""
    later = close[close.index >= t + pd.Timedelta(hours=hours)]
    return None if later.empty else float(later.iloc[0] / price - 1)


def trades(strat: dict, close: pd.Series) -> pd.DataFrame:
    rows = []
    for tr in strat["trades"]:
        t_open = pd.Timestamp(tr["open_timestamp"], unit="ms", tz="UTC")
        t_close = pd.Timestamp(tr["close_timestamp"], unit="ms", tz="UTC")
        cp = float(tr["close_rate"])
        rows.append({
            "open": t_open, "close": t_close, "year": t_open.year, "exit": tr["exit_reason"],
            "pnl": float(tr["profit_abs"]), "pct": 100 * float(tr["profit_ratio"]),
            "days": (t_close - t_open).total_seconds() / 86400,
            "after_3d": fwd_return(close, t_close, cp, 72), "after_14d": fwd_return(close, t_close, cp, 336),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result")
    ap.add_argument("--split", default="2024-12-12", help="in-sample / out-of-sample boundary")
    ap.add_argument("--json")
    args = ap.parse_args()

    strat, _w, market = load(Path(args.result))
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"], utc=True)
    df = trades(strat, m.set_index("date")["mean"])
    if df.empty:
        print(f"== {strat['_name']}: no trades")
        return
    cut = pd.Timestamp(args.split, tz="UTC")
    df["segment"] = (df["open"] >= cut).map({False: "in_sample", True: "out_of_sample"})
    pd.set_option("display.width", 160)
    wins = df[df.pnl > 0]
    print(f"== {strat['_name']}  trades {len(df)}  pnl {df.pnl.sum():.0f}  win rate {100 * len(wins) / len(df):.0f}%  "
          f"avg hold {df.days.mean():.1f} d")
    print("\nby year:")
    g = df.groupby("year")
    print(pd.DataFrame({"n": g.size(), "pnl": g.pnl.sum().round(0), "best_%": g.pct.max().round(1),
                        "worst_%": g.pct.min().round(1)}).to_string())
    print("\nby exit reason:")
    g = df.groupby("exit")
    print(pd.DataFrame({
        "n": g.size(), "pnl": g.pnl.sum().round(0), "avg_days": g.days.mean().round(1),
        "px_after_3d_%": (100 * g.after_3d.mean()).round(2), "px_after_14d_%": (100 * g.after_14d.mean()).round(2),
        "share_higher_3d_%": (100 * g.after_3d.apply(lambda s: (s > 0).mean())).round(0),
    }).to_string())
    print("\nby segment:")
    print(df.groupby("segment")[["pnl"]].agg(["count", "sum"]).round(0).to_string())
    if args.json:
        Path(args.json).write_text(df.to_json(orient="records", date_format="iso", indent=1))


if __name__ == "__main__":
    main()
