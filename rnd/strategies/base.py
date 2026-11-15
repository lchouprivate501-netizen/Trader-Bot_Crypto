"""策略介面（研發部「寫程式」角色的模板）。

每個策略只需要定義：
- NAME / DESCRIPTION / TIMEFRAME
- DEFAULTS：預設參數
- SPACE：可優化的參數（少量；name -> (low, high, "int"|"float")）
- signals(df, params) -> DataFrame，欄位 long, short (bool), sl_long, tp_long, sl_short, tp_short
  df 是已收盤的 5m K 線（ts=開盤時間, UTC），並已附上 1h 欄位（h_*，只用已收盤的 1h K）。
訊號在 K 線收盤時判定、以收盤價進場，絕不使用未來資料。
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def session_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df.high + df.low + df.close) / 3
    day = df.ts.dt.floor("1D")
    pv = (tp * df.volume).groupby(day).cumsum()
    v = df.volume.groupby(day).cumsum().replace(0, np.nan)
    return pv / v


def attach_htf(df5: pd.DataFrame, df1h: pd.DataFrame) -> pd.DataFrame:
    """Join closed 1h bars onto 5m bars without look-ahead (match on bar close time)."""
    h = df1h.copy()
    h["h_ema50"] = ema(h.close, 50)
    h["h_ema200"] = ema(h.close, 200)
    h["h_slope"] = h["h_ema50"].diff(3)
    h["h_close"] = h.close
    h["close_time"] = h.ts + pd.Timedelta(hours=1)
    h = h[["close_time", "h_ema50", "h_ema200", "h_slope", "h_close"]]
    d = df5.copy()
    d["close_time"] = d.ts + pd.Timedelta(minutes=5)
    d = pd.merge_asof(d.sort_values("close_time"), h.sort_values("close_time"), on="close_time", direction="backward")
    return d.drop(columns=["close_time"])


def finalize(df: pd.DataFrame, long, short, sl_long, sl_short, rr: float) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    c = df.close
    out["long"] = (long & (sl_long < c)).fillna(False)
    out["short"] = (short & (sl_short > c)).fillna(False)
    out["sl_long"], out["sl_short"] = sl_long, sl_short
    out["tp_long"] = c + rr * (c - sl_long)
    out["tp_short"] = c - rr * (sl_short - c)
    return out
