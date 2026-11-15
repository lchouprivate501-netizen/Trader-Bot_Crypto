"""S3 波動率擠壓突破（5m）。
布林帶寬落在近 200 根的 squeeze_pct 分位以下（擠壓）後，收盤突破前 20 根唐奇安通道，方向需與 1h EMA50 一致。
停損：進場價 −/+ k_atr×ATR；停利 rr×R。"""
from rnd.strategies.base import atr, finalize

NAME = "vol_breakout"
DESCRIPTION = "布林擠壓後唐奇安突破 + 1h 趨勢一致"
TIMEFRAME = "5m"
DEFAULTS = {"squeeze_pct": 0.2, "k_atr": 1.5, "rr": 1.5, "max_hold": 36}
SPACE = {"squeeze_pct": (0.05, 0.4, "float"), "k_atr": (0.8, 3.0, "float"), "rr": (1.0, 3.0, "float")}


def signals(df, p):
    a = atr(df, 14)
    m = df.close.rolling(20).mean()
    sd = df.close.rolling(20).std()
    width = (4 * sd / m)
    q = width.rolling(200).quantile(p["squeeze_pct"])
    squeezed = (width.shift(1) <= q.shift(1))
    hi = df.high.shift(1).rolling(20).max()
    lo = df.low.shift(1).rolling(20).min()
    long = squeezed & (df.close > hi) & (df.h_close > df.h_ema50)
    short = squeezed & (df.close < lo) & (df.h_close < df.h_ema50)
    sl_l = df.close - p["k_atr"] * a
    sl_s = df.close + p["k_atr"] * a
    return finalize(df, long, short, sl_l, sl_s, p["rr"])


def near(df, p):
    """處於擠壓中且收盤距唐奇安邊界越近分數越高。"""
    a = atr(df, 14).iloc[-1]
    m, sd = df.close.rolling(20).mean(), df.close.rolling(20).std()
    w = 4 * sd / m
    sq = w.iloc[-1] <= w.rolling(200).quantile(p["squeeze_pct"]).iloc[-1]
    r = df.iloc[-1]
    hi, lo = df.high.iloc[-20:].max(), df.low.iloc[-20:].min()
    d = min((hi - r.close) / a if r.h_close > r.h_ema50 else 99, (r.close - lo) / a if r.h_close < r.h_ema50 else 99)
    return round(float(max(0.0, 1 - d / 3)) if sq else 0.0, 3)
