#!/usr/bin/env python3
"""Download Binance public archive data (data.binance.vision) into Freqtrade's data layout.

Why: `freqtrade download-data` needs the exchange REST API, which is slow for multi-year
history and is geo-blocked in many cloud regions. data.binance.vision serves the same
candles as monthly zip files with no key and no rate limit.

What it writes (Freqtrade feather format, via Freqtrade's own data handler):
  spot:     <datadir>/BTC_USDT-1h.feather (+ every --timeframes, + resampled 4h/1d)
  futures:  <datadir>/futures/BTC_USDT_USDT-1h-futures.feather
            <datadir>/futures/BTC_USDT_USDT-1h-mark.feather
            <datadir>/futures/BTC_USDT_USDT-1h-funding_rate.feather

Run it with the Python of the Freqtrade venv, e.g.
  python download_binance_vision.py --pairs BTC/USDT ETH/USDT SOL/USDT \
      --timeframes 1h 5m --start 2020-06 --end 2026-10 --trading-mode spot \
      --datadir user_data/data/binance
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import requests

BASE = "https://data.binance.vision/data"
RESAMPLE = {"4h": "4h", "1d": "1D"}
OHLCV = ["date", "open", "high", "low", "close", "volume"]


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ye, me = map(int, end.split("-"))
    out = []
    while (y, m) <= (ye, me):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch_zip_csv(url: str, retries: int = 4) -> pd.DataFrame | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                raw = zf.read(zf.namelist()[0]).decode()
            first = raw.split("\n", 1)[0]
            header = 0 if any(c.isalpha() for c in first.split(",")[0]) else None
            return pd.read_csv(io.StringIO(raw), header=header)
        except Exception as exc:  # network hiccup -> retry with backoff
            if attempt == retries - 1:
                print(f"  ! giving up on {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(2**attempt)
    return None


def to_ts(col: pd.Series) -> pd.Series:
    col = pd.to_numeric(col).astype("int64")
    # Binance switched spot archives from milliseconds to microseconds in 2025,
    # so a multi-year download mixes both units: normalise row by row.
    col = col.where(col < 10**14, col // 1000)
    return pd.to_datetime(col, unit="ms", utc=True)


def klines(symbol: str, tf: str, months_: list[str], market: str, kind: str = "klines") -> pd.DataFrame:
    root = f"{BASE}/spot/monthly/{kind}" if market == "spot" else f"{BASE}/futures/um/monthly/{kind}"
    urls = [f"{root}/{symbol}/{tf}/{symbol}-{tf}-{mo}.zip" for mo in months_]
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = [f for f in pool.map(fetch_zip_csv, urls) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=OHLCV)
    df = pd.concat([f.iloc[:, :6].set_axis(OHLCV, axis=1) for f in frames], ignore_index=True)
    df["date"] = to_ts(df["date"])
    for c in OHLCV[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    return df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)


def funding(symbol: str, months_: list[str]) -> pd.DataFrame:
    urls = [f"{BASE}/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{mo}.zip" for mo in months_]
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = [f for f in pool.map(fetch_zip_csv, urls) if f is not None and len(f)]
    if not frames:
        return pd.DataFrame(columns=["date", "funding_rate"])
    df = pd.concat(frames, ignore_index=True)
    df.columns = [str(c) for c in df.columns]
    tcol = "calc_time" if "calc_time" in df.columns else df.columns[0]
    rcol = "last_funding_rate" if "last_funding_rate" in df.columns else df.columns[-1]
    out = pd.DataFrame({"date": to_ts(df[tcol]).dt.floor("h"), "funding_rate": pd.to_numeric(df[rcol])})
    return out.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    r = df.set_index("date").resample(rule, label="left", closed="left")
    out = r.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna().reset_index()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", nargs="+", default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    ap.add_argument("--timeframes", nargs="+", default=["1h", "5m"])
    ap.add_argument("--start", default="2020-06", help="first month YYYY-MM")
    ap.add_argument("--end", default=f"{date.today():%Y-%m}", help="last month YYYY-MM (missing months are skipped)")
    ap.add_argument("--trading-mode", choices=["spot", "futures"], default="spot")
    ap.add_argument("--datadir", default="user_data/data/binance")
    args = ap.parse_args()

    from freqtrade.data.history import get_datahandler  # imported late so --help works anywhere
    from freqtrade.enums import CandleType

    futures = args.trading_mode == "futures"
    datadir = Path(args.datadir)
    handler = get_datahandler(datadir, "feather")
    mos = months(args.start, args.end)
    market = "futures" if futures else "spot"
    main_type = CandleType.FUTURES if futures else CandleType.SPOT

    for pair in args.pairs:
        base, quote = pair.split("/")[0], pair.split("/")[1].split(":")[0]
        symbol = f"{base}{quote}"
        ft_pair = f"{base}/{quote}:{quote}" if futures else f"{base}/{quote}"
        for tf in args.timeframes:
            df = klines(symbol, tf, mos, market)
            if df.empty:
                print(f"{pair} {tf}: no data")
                continue
            handler.ohlcv_store(ft_pair, tf, df, main_type)
            print(f"{ft_pair} {tf} {main_type.value}: {len(df)} rows {df.date.iloc[0]} -> {df.date.iloc[-1]}")
            if tf == "1h":
                for name, rule in RESAMPLE.items():
                    if name not in args.timeframes:
                        handler.ohlcv_store(ft_pair, name, resample(df, rule), main_type)
                        print(f"  resampled -> {name}")
        if futures:
            mark = klines(symbol, "1h", mos, market, kind="markPriceKlines")
            handler.ohlcv_store(ft_pair, "1h", mark, CandleType.MARK)
            fr = funding(symbol, mos)
            handler.ohlcv_store(ft_pair, "1h", fr, CandleType.FUNDING_RATE)
            print(f"  mark {len(mark)} rows, funding {len(fr)} rows")


if __name__ == "__main__":
    main()
