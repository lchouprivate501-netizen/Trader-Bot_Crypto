"""OKX public market data (no API key). Used only for data; orders go through Pionex in the browser."""
from __future__ import annotations
import time
import pandas as pd
import requests

BASE = "https://www.okx.com"
_S = requests.Session()
_S.headers["User-Agent"] = "trading-company/1.0"
BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
OKX_BAR = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H"}


def inst(sym: str) -> str:
    return f"{sym}-USDT-SWAP"


def _get(path: str, params: dict, retries: int = 5):
    for i in range(retries):
        try:
            r = _S.get(BASE + path, params=params, timeout=15)
            if r.status_code == 429:
                time.sleep(1 + i); continue
            r.raise_for_status()
            j = r.json()
            if j.get("code") not in ("0", 0):
                if j.get("code") == "50011":
                    time.sleep(1 + i); continue
                raise RuntimeError(f"OKX error {j}")
            return j["data"]
        except (requests.RequestException, ValueError):
            if i == retries - 1:
                raise
            time.sleep(1 + i)
    raise RuntimeError("OKX rate limited")


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volQuote", "confirm"])
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    for c in ["open", "high", "low", "close", "volQuote"]:
        df[c] = df[c].astype(float)
    df = df.rename(columns={"volQuote": "volume"})
    df["confirm"] = df["confirm"].astype(int)
    return df[["ts", "open", "high", "low", "close", "volume", "confirm"]].sort_values("ts").reset_index(drop=True)


def history(sym: str, tf: str, start_ms: int, end_ms: int | None = None, sleep: float = 0.11) -> pd.DataFrame:
    """Page backwards from end to start (history-candles, 100/request)."""
    end_ms = end_ms or int(time.time() * 1000)
    after, out = end_ms, []
    while True:
        rows = _get("/api/v5/market/history-candles", {"instId": inst(sym), "bar": OKX_BAR[tf], "after": str(after), "limit": "100"})
        if not rows:
            break
        out.extend(rows)
        oldest = int(rows[-1][0])
        if oldest <= start_ms:
            break
        after = oldest
        time.sleep(sleep)
    if not out:
        return _frame([])
    df = _frame(out)
    return df[(df.ts >= pd.Timestamp(start_ms, unit="ms", tz="UTC"))].drop_duplicates("ts")


def recent(sym: str, tf: str, limit: int = 300) -> pd.DataFrame:
    rows = _get("/api/v5/market/candles", {"instId": inst(sym), "bar": OKX_BAR[tf], "limit": str(min(limit, 300))})
    return _frame(rows)


def tickers() -> list[dict]:
    return _get("/api/v5/market/tickers", {"instType": "SWAP"})
