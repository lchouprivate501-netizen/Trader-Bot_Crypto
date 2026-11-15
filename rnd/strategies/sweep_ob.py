"""S2 聰明錢短線：流動性掃蕩 + 訂單塊確認（純程式實作，不用 smartmoneyconcepts 套件）。
多：本根低點刺破前 lookback 根的最低點（掃停損）但收盤收回其上，且收在 K 線上半部、成交量 > vol_mult×20 根均量
（吸收＝訂單塊），並且 1h 收盤在 1h EMA200 之上。空：鏡像。停損：掃蕩極值外 0.1 ATR；停利 rr×R。"""
from rnd.strategies.base import atr, finalize

NAME = "sweep_ob"
DESCRIPTION = "流動性掃蕩 + 放量收回（訂單塊）+ 1h EMA200 方向"
TIMEFRAME = "5m"
DEFAULTS = {"lookback": 24, "rr": 1.5, "vol_mult": 1.5, "max_hold": 36}
SPACE = {"lookback": (10, 48, "int"), "rr": (1.0, 2.5, "float"), "vol_mult": (1.0, 2.5, "float")}


def signals(df, p):
    a = atr(df, 14)
    n = int(p["lookback"])
    prev_low = df.low.shift(1).rolling(n).min()
    prev_high = df.high.shift(1).rolling(n).max()
    rng = (df.high - df.low).replace(0, float("nan"))
    pos = (df.close - df.low) / rng
    vol_ok = df.volume > p["vol_mult"] * df.volume.rolling(20).mean().shift(1)
    long = (df.low < prev_low) & (df.close > prev_low) & (pos > 0.5) & vol_ok & (df.h_close > df.h_ema200)
    short = (df.high > prev_high) & (df.close < prev_high) & (pos < 0.5) & vol_ok & (df.h_close < df.h_ema200)
    sl_l = df.low - 0.1 * a
    sl_s = df.high + 0.1 * a
    return finalize(df, long, short, sl_l, sl_s, p["rr"])


def near(df, p):
    """收盤距前 lookback 根高/低點（流動性池）幾個 ATR；越近越可能出現掃蕩。"""
    a = atr(df, 14).iloc[-1]
    n = int(p["lookback"])
    r = df.iloc[-1]
    lo, hi = df.low.iloc[-n - 1:-1].min(), df.high.iloc[-n - 1:-1].max()
    d_long = (r.close - lo) / a if r.h_close > r.h_ema200 else 99
    d_short = (hi - r.close) / a if r.h_close < r.h_ema200 else 99
    return round(float(max(0.0, 1 - min(d_long, d_short) / 4)), 3)
