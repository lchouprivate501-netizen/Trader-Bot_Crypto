"""研發部資料下載：OKX 公開 K 線 → rnd/data/<SYM>_<tf>.parquet（增量更新）。
用法: python -m rnd.data --days 365 --tf 5m [--symbols BTC,ETH]
15m/1h 由 5m 重採樣產生（load(..., '1h')），1m 可選下載作為成交細節。"""
from __future__ import annotations
import argparse, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from company import okx
from company.paths import DATA, universe


def path(sym: str, tf: str):
    return DATA / f"{sym}_{tf}.parquet"


def update(sym: str, tf: str, days: int) -> str:
    p = path(sym, tf)
    now = int(time.time() * 1000)
    start = now - days * 86_400_000
    old = pd.read_parquet(p) if p.exists() else None
    if old is not None and len(old):
        first, last = int(old.ts.iloc[0].value // 1e6), int(old.ts.iloc[-1].value // 1e6)
        parts = [old]
        if first > start + okx.BAR_MS[tf]:
            parts.append(okx.history(sym, tf, start, first))
        parts.append(okx.history(sym, tf, last, now))
        df = pd.concat(parts)
    else:
        df = okx.history(sym, tf, start, now)
    df = df[df.confirm == 1].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df.to_parquet(p, index=False)
    return f"{sym} {tf}: {len(df)} bars {df.ts.iloc[0] if len(df) else '-'} → {df.ts.iloc[-1] if len(df) else '-'}"


def load(sym: str, tf: str = "5m") -> pd.DataFrame:
    if tf in ("15m", "1h") and not path(sym, tf).exists():
        base = pd.read_parquet(path(sym, "5m")).set_index("ts")
        rule = {"15m": "15min", "1h": "1h"}[tf]
        agg = base.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        return agg.reset_index()
    return pd.read_parquet(path(sym, tf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    syms = a.symbols.split(",") if a.symbols else universe()["backtest_symbols"]
    with ThreadPoolExecutor(a.workers) as ex:
        for msg in ex.map(lambda s: update(s, a.tf, a.days), syms):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
