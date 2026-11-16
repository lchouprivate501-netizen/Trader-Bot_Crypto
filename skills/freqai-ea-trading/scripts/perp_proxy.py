#!/usr/bin/env python3
"""Extend Binance USDT-M perpetual history backwards with spot prices (futures V1 validation only).

data.binance.vision has USDT-M perpetual candles only from 2020-01. The futures EA protocol
(references/futures-validation-protocol.md) tests BTC and ETH on 2018-06 .. 2021-06, so for the
months before the first real perpetual candle this script uses the spot candles as a proxy:

  <pair>-1h-futures, <pair>-15m-futures, <pair>-1h-mark   <- spot 1h / 15m candles before the first perp candle
  <pair>-1h-funding_rate                                 <- 0.0 every 8 hours before the first funding record

Real perpetual data is never modified: only rows strictly earlier than the first real row are
added. Perpetual and spot prices differ by a small basis, and funding is set to zero where none
existed, so results in the proxy months are an approximation (stated in the protocol).
A PROXY.json file next to the data records exactly which rows are proxies.

Usage (Freqtrade venv): python perp_proxy.py --datadir user_data/data/binance --pairs BTC/USDT ETH/USDT
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def prepend(real: pd.DataFrame, proxy: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    first = real["date"].min()
    add = proxy[proxy["date"] < first]
    out = pd.concat([add, real], ignore_index=True).sort_values("date").reset_index(drop=True)
    return out, len(add)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--pairs", nargs="+", default=["BTC/USDT", "ETH/USDT"])
    a = ap.parse_args()
    d = Path(a.datadir)
    fut = d / "futures"
    log = json.loads((fut / "PROXY.json").read_text()) if (fut / "PROXY.json").exists() else {}
    for pair in a.pairs:
        base, quote = pair.split("/")
        spot, perp = f"{base}_{quote}", f"{base}_{quote}_{quote}"
        entry = log.setdefault(pair, {})
        for tf, kind, src_tf in (("1h", "futures", "1h"), ("15m", "futures", "15m"), ("1h", "mark", "1h")):
            f = fut / f"{perp}-{tf}-{kind}.feather"
            real = pd.read_feather(f)
            src = pd.read_feather(d / f"{spot}-{src_tf}.feather")[list(real.columns)]
            out, n = prepend(real, src)
            if n:
                out.to_feather(f)
                entry[f.name] = {"proxy_rows": n, "proxy_from": str(out["date"].min()), "real_from": str(real["date"].min())}
            print(f"{f.name}: +{n} spot rows (real data from {real['date'].min()})")
        f = fut / f"{perp}-1h-funding_rate.feather"
        real = pd.read_feather(f)
        spot1h = pd.read_feather(d / f"{spot}-1h.feather")
        grid = pd.date_range(spot1h["date"].min().ceil("8h"), real["date"].min(), freq="8h", inclusive="left")
        out, n = prepend(real, pd.DataFrame({"date": grid.astype(real["date"].dtype), "funding_rate": 0.0}))
        if n:
            out.to_feather(f)
            entry[f.name] = {"proxy_rows": n, "proxy_from": str(out["date"].min()), "real_from": str(real["date"].min()),
                             "proxy_value": 0.0}
        print(f"{f.name}: +{n} zero-funding rows (real funding from {real['date'].min()})")
    (fut / "PROXY.json").write_text(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
