#!/usr/bin/env python3
"""How informative are the cached FreqAI walk-forward predictions?

Reads user_data/models/<identifier>/backtesting_predictions/*.feather (written by a FreqAI
backtest), recomputes the realised targets from the candle data and prints, per year:
  * vol:   Spearman rank correlation of predicted vs realised forward sigma, the same for
           the naive forecast (trailing sigma), and the realised-sigma ratio between the
           top and bottom prediction quintiles;
  * trend: rank correlation (information coefficient) of predicted vs realised drift, and
           the mean realised drift when the z-score is < -1, in [-1, 1] and > 1.
Every prediction was made out-of-sample (walk-forward), so this is an honest skill check.

Usage: python prediction_quality.py --identifier ea-btc-v1 --pair BTC/USDT \
           --datadir user_data/data/binance --models user_data/models [--horizon 72]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--identifier", required=True)
    ap.add_argument("--pair", required=True, help="e.g. BTC/USDT or ETH/USDT:USDT")
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--models", default="user_data/models")
    ap.add_argument("--horizon", type=int, default=72, help="label_period_candles")
    ap.add_argument("--vol-horizon", type=int, default=24)
    args = ap.parse_args()

    files = sorted((Path(args.models) / args.identifier / "backtesting_predictions").glob("*.feather"))
    pred = pd.concat([pd.read_feather(f) for f in files]).drop_duplicates("date").set_index("date")
    base, rest = args.pair.split("/")
    if ":" in rest:
        candles = Path(args.datadir) / "futures" / f"{base}_{rest.replace(':', '_')}-1h-futures.feather"
    else:
        candles = Path(args.datadir) / f"{base}_{rest}-1h.feather"
    c = pd.read_feather(candles).set_index("date")["close"]
    logc = np.log(c)
    ret = logc.diff()
    trail_vol = ret.rolling(args.vol_horizon).std()
    real_vol = trail_vol.shift(-args.vol_horizon)
    real_trend = logc.rolling(args.horizon).mean().shift(-args.horizon) - logc
    df = pred.join(
        pd.DataFrame({"real_vol": real_vol, "real_trend": real_trend, "trail_vol": trail_vol}), how="inner"
    ).dropna()
    if "&-vol_ratio" in df:  # v2 targets: vol ratio + vol-normalised drift
        df["&-vol"] = df["trail_vol"] * np.exp(df["&-vol_ratio"])
        df["&-trend"], df["&-trend_mean"], df["&-trend_std"] = df["&-drift"], df["&-drift_mean"], df["&-drift_std"]
    df["z"] = (df["&-trend"] - df["&-trend_mean"]) / df["&-trend_std"]

    print(f"{args.identifier}: {len(files)} windows, {len(df)} hourly predictions "
          f"{df.index[0].date()} -> {df.index[-1].date()}")
    print(f"{'year':>6s} {'volIC':>7s} {'naiveIC':>7s} {'volQ5/Q1':>9s} {'trendIC':>8s} "
          f"{'drift|z<-1':>11s} {'drift|mid':>10s} {'drift|z>1':>10s} {'%z<-1':>6s} {'%z>1':>6s}")
    for year, g in [*df.groupby(df.index.year), ("all", df)]:
        vic = g["&-vol"].corr(g["real_vol"], method="spearman")
        nic = g["trail_vol"].corr(g["real_vol"], method="spearman")
        q = pd.qcut(g["&-vol"], 5, labels=False, duplicates="drop")
        ratio = g["real_vol"][q == q.max()].mean() / g["real_vol"][q == q.min()].mean()
        tic = g["&-trend"].corr(g["real_trend"], method="spearman")
        lo, hi = g["z"] < -1, g["z"] > 1
        mid = ~lo & ~hi
        print(
            f"{year!s:>6s} {vic:7.3f} {nic:7.3f} {ratio:9.2f} {tic:8.3f} "
            f"{100 * g['real_trend'][lo].mean():10.2f}% {100 * g['real_trend'][mid].mean():9.2f}% "
            f"{100 * g['real_trend'][hi].mean():9.2f}% {100 * lo.mean():5.1f}% {100 * hi.mean():5.1f}%"
        )


if __name__ == "__main__":
    main()
