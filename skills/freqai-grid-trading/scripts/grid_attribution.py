#!/usr/bin/env python3
"""Where does a grid backtest make and lose its money?

Rebuilds every session's LIFO lot ledger from the exported orders (same rules as
GridAIBase) and splits each session's PnL into
  grid      realised profit of grid round trips (lot bought, then sold one step higher),
            fees included;
  inventory everything else: anchor/core and lots still open when the session ended,
            closed at the session exit (fees included).
It also reports, per exit reason, what price did after the exit (did a stop sell the low?).

Usage: python grid_attribution.py <result.zip> [--datadir user_data/data/binance] [--json out.json]
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
from grid_report import load  # noqa: E402


def anchor_share(p: dict) -> float:
    cf = float(p["core_frac"])
    if cf <= 0:
        return 1.0
    lot = (1 - cf) / int(p["max_lots"])
    return cf / (cf + lot)


def fwd_return(close: pd.Series, t: pd.Timestamp, price: float, hours: int) -> float | None:
    """Price change from an exit price to the first close at least `hours` later."""
    later = close[close.index >= t + pd.Timedelta(hours=hours)]
    return None if later.empty else float(later.iloc[0] / price - 1)


def sessions(strat: dict, p: dict, close: pd.Series) -> pd.DataFrame:
    rows = []
    share = anchor_share(p)
    for tr in strat["trades"]:
        side = -1.0 if tr.get("is_short") else 1.0
        fee_o, fee_c = float(tr["fee_open"]), float(tr["fee_close"])
        lots: list[list[float]] = []  # [price, amount]
        grid_pnl, n_rt = 0.0, 0
        first = True
        for od in sorted(tr.get("orders", []), key=lambda o: o["order_filled_timestamp"]):
            amt, px, tag = float(od["amount"]), float(od["safe_price"]), od.get("ft_order_tag")
            if od["ft_is_entry"]:
                if first:
                    first = False
                    if share < 1:
                        lots.append([px, amt * (1 - share)])
                elif tag == "grid_buy":
                    lots.append([px, amt])
            elif tag == "grid_sell":
                rem = amt
                while lots and rem > 1e-12:
                    bp, ba = lots[-1]
                    take = min(ba, rem)
                    grid_pnl += side * take * (px - bp) - take * (px * fee_c + bp * fee_o)
                    rem -= take
                    if ba - take <= 1e-6 * ba:  # same tolerance as GridAIBase (rounding dust)
                        lots.pop()
                        rem = 0.0 if rem <= 1e-6 * ba else rem
                    else:
                        lots[-1][1] -= take
                n_rt += 1
        t_open = pd.Timestamp(tr["open_timestamp"], unit="ms", tz="UTC")
        t_close = pd.Timestamp(tr["close_timestamp"], unit="ms", tz="UTC")
        cp = float(tr["close_rate"])

        rows.append(
            {
                "open": t_open,
                "close": t_close,
                "year": t_open.year,
                "exit": tr["exit_reason"],
                "pnl": float(tr["profit_abs"]),
                "grid_pnl": grid_pnl,
                "inv_pnl": float(tr["profit_abs"]) - grid_pnl,
                "round_trips": n_rt,
                "open_lots_at_exit": len(lots),
                "hours": (t_close - t_open).total_seconds() / 3600,
                "after_3d": fwd_return(close, t_close, cp, 72),
                "after_14d": fwd_return(close, t_close, cp, 336),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result")
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--split", default="2024-12-12")
    ap.add_argument("--json")
    args = ap.parse_args()

    strat, _w, market = load(Path(args.result))
    import zipfile

    with zipfile.ZipFile(args.result) as zf:
        cfg = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("_config.json"))))
    sys.path.insert(0, str(SKILL / "user_data/strategies"))
    cls = getattr(importlib.import_module(strat["_name"]), strat["_name"])
    p = {**cls.GRID, **cfg.get("grid_params", {})}
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"], utc=True)
    close = m.set_index("date")["mean"]

    df = sessions(strat, p, close)
    cut = pd.Timestamp(args.split, tz="UTC")
    df["segment"] = (df["open"] >= cut).map({False: "in_sample", True: "out_of_sample"})
    pd.set_option("display.width", 160)
    print(f"== {strat['_name']}  sessions {len(df)}  total {df.pnl.sum():.0f}  "
          f"grid {df.grid_pnl.sum():.0f}  inventory {df.inv_pnl.sum():.0f}")
    print("\nby year:")
    print(df.groupby("year")[["pnl", "grid_pnl", "inv_pnl", "round_trips"]].sum().round(0).to_string())
    print("\nby exit reason:")
    g = df.groupby("exit")
    print(pd.DataFrame({
        "n": g.size(), "pnl": g.pnl.sum().round(0), "grid": g.grid_pnl.sum().round(0),
        "inventory": g.inv_pnl.sum().round(0), "avg_hours": g.hours.mean().round(0),
        "px_after_3d_%": (100 * g.after_3d.mean()).round(2), "px_after_14d_%": (100 * g.after_14d.mean()).round(2),
        "share_higher_3d_%": (100 * g.after_3d.apply(lambda s: (s > 0).mean())).round(0),
    }).to_string())
    print("\nby segment:")
    print(df.groupby("segment")[["pnl", "grid_pnl", "inv_pnl"]].sum().round(0).to_string())
    if args.json:
        Path(args.json).write_text(df.to_json(orient="records", date_format="iso", indent=1))


if __name__ == "__main__":
    main()
