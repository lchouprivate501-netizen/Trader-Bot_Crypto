"""S4 1h 趨勢回檔（RSI 收回），只在 1h K 收盤時判定（v4，2026-11-15 研發部）。
與前三版（5m 進出）真正不同：訊號週期 1h、停損用 1h ATR（較寬 → 單筆可用滿 0.5% 風險、手續費占 R 比例低）、持有數小時到兩天。
多：1h 收盤 > 1h EMA200 且 EMA50 > EMA200；前一根 1h RSI(14) < rsi_lo，本根收回 ≥ rsi_lo 且收紅K。
空：鏡像（收盤 < EMA200、EMA50 < EMA200；RSI 從 > 100-rsi_lo 回落）。
停損：近 3 根 1h 極值外加 sl_atr × 1h ATR；停利：rr × R；最長持有 max_hold 根 5m。
1h 指標由已收盤的 5m 重採樣而得，只合併到該 1h 收盤那根 5m（ts 分鐘=55），以收盤價進場，無未來資料。"""
import numpy as np
import pandas as pd
from rnd.strategies.base import atr, ema, rsi, finalize

NAME = "h1_trend_rsi_pullback"
DESCRIPTION = "1h 趨勢（EMA50/200）中 RSI 回檔收回進場，1h ATR 寬停損，長持有"
TIMEFRAME = "1h"
DEFAULTS = {"rsi_lo": 40.0, "rr": 2.0, "sl_atr": 1.0, "max_hold": 288}
SPACE = {"rsi_lo": (30.0, 45.0, "float"), "rr": (1.2, 3.0, "float"), "sl_atr": (0.5, 2.0, "float"), "max_hold": (96, 576, "int")}


def _h1(df: pd.DataFrame, p) -> pd.DataFrame:
    base = df.set_index("ts")[["open", "high", "low", "close", "volume"]]
    h = base.resample("1h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    h["e50"], h["e200"] = ema(h.close, 50), ema(h.close, 200)
    h["r"] = rsi(h.close, 14)
    h["a"] = atr(h, 14)
    lo, hi = p["rsi_lo"], 100 - p["rsi_lo"]
    up = (h.close > h.e200) & (h.e50 > h.e200)
    dn = (h.close < h.e200) & (h.e50 < h.e200)
    h["L"] = up & (h.r.shift() < lo) & (h.r >= lo) & (h.close > h.open)
    h["S"] = dn & (h.r.shift() > hi) & (h.r <= hi) & (h.close < h.open)
    h["SLL"] = h.low.rolling(3).min() - p["sl_atr"] * h.a
    h["SLS"] = h.high.rolling(3).max() + p["sl_atr"] * h.a
    h["close_time"] = h.ts + pd.Timedelta(hours=1)
    return h[["close_time", "L", "S", "SLL", "SLS"]]


def signals(df, p):
    h = _h1(df, p)
    ct = df.ts + pd.Timedelta(minutes=5)
    m = pd.DataFrame({"close_time": ct}).merge(h, on="close_time", how="left")
    m.index = df.index
    long = m.L.eq(True)
    short = m.S.eq(True)
    return finalize(df, long, short, m.SLL, m.SLS, p["rr"])


def near(df, p):
    """0–1：1h RSI 離回檔門檻多近（趨勢成立才給分）。"""
    q = dict(DEFAULTS, **(p or {}))
    base = df.set_index("ts")[["open", "high", "low", "close"]]
    h = base.resample("1h", label="left", closed="left").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(h) < 210:
        return 0.0
    e50, e200, r = ema(h.close, 50).iloc[-1], ema(h.close, 200).iloc[-1], rsi(h.close, 14).iloc[-1]
    c = h.close.iloc[-1]
    if c > e200 and e50 > e200:
        d = max(0.0, r - q["rsi_lo"])
    elif c < e200 and e50 < e200:
        d = max(0.0, (100 - q["rsi_lo"]) - r)
    else:
        return 0.0
    return round(float(max(0.0, 1 - d / 20)), 3)
