"""S1 VWAP/EMA 回踩（5m，1h 趨勢過濾）。
多：1h 收盤 > 1h EMA50 且 EMA50 上彎；5m 低點回踩到當日 VWAP 或 EMA20 附近（0.25 ATR 內）後收回其上、收紅K。
空：鏡像。停損：近 3 根極值外加 sl_buf×ATR；停利：rr×R；最長持有 max_hold 根。"""
from rnd.strategies.base import atr, ema, session_vwap, finalize

NAME = "vwap_pullback"
DESCRIPTION = "5m 回踩 VWAP/EMA20 + 1h EMA50 趨勢過濾"
TIMEFRAME = "5m"
DEFAULTS = {"rr": 1.5, "sl_buf": 0.3, "max_hold": 36}
SPACE = {"rr": (1.0, 2.5, "float"), "sl_buf": (0.1, 0.8, "float"), "max_hold": (12, 72, "int")}


def signals(df, p):
    a = atr(df, 14)
    vw = session_vwap(df)
    e20 = ema(df.close, 20)
    up = (df.h_close > df.h_ema50) & (df.h_slope > 0)
    dn = (df.h_close < df.h_ema50) & (df.h_slope < 0)
    near_l = ((df.low - vw).abs() < 0.25 * a) | ((df.low - e20).abs() < 0.25 * a)
    near_s = ((df.high - vw).abs() < 0.25 * a) | ((df.high - e20).abs() < 0.25 * a)
    long = up & near_l & (df.close > vw) & (df.close > e20) & (df.close > df.open)
    short = dn & near_s & (df.close < vw) & (df.close < e20) & (df.close < df.open)
    sl_l = df.low.rolling(3).min() - p["sl_buf"] * a
    sl_s = df.high.rolling(3).max() + p["sl_buf"] * a
    return finalize(df, long, short, sl_l, sl_s, p["rr"])


def near(df, p):
    """0–1：離觸發多近（給 shortlist 用）。趨勢成立且收盤離 VWAP/EMA20 越近分數越高。"""
    a = atr(df, 14).iloc[-1]
    vw, e20 = session_vwap(df).iloc[-1], ema(df.close, 20).iloc[-1]
    r = df.iloc[-1]
    trend = (r.h_close > r.h_ema50 and r.h_slope > 0) or (r.h_close < r.h_ema50 and r.h_slope < 0)
    dist = min(abs(r.close - vw), abs(r.close - e20)) / a if a > 0 else 99
    return round(float(max(0.0, 1 - dist / 3)) if trend else 0.0, 3)
