"""執行部「分析」角色：純規則的多時間框架分析（5m/15m/1h/4h），不使用任何 LLM。
每個框架：EMA20/EMA50 關係與斜率、RSI14、ATR%；另附 OKX 資金費率與距近 24h 高低點。
結論 aligned_long / aligned_short / mixed，以及與提議方向是否一致。"""
from __future__ import annotations
from company import okx
from rnd.strategies.base import atr, ema, rsi


def _tf(sym, tf):
    d = okx.recent(sym, tf, 300)
    d = d[d.confirm == 1]
    e20, e50 = ema(d.close, 20), ema(d.close, 50)
    c = d.close.iloc[-1]
    trend = "up" if c > e20.iloc[-1] > e50.iloc[-1] and e50.diff(3).iloc[-1] > 0 else (
        "down" if c < e20.iloc[-1] < e50.iloc[-1] and e50.diff(3).iloc[-1] < 0 else "flat")
    return {"trend": trend, "rsi": round(float(rsi(d.close).iloc[-1]), 1), "atr_pct": round(float(atr(d).iloc[-1] / c * 100), 3),
            "close": float(c), "hi_24h": float(d.high.tail({"5m": 288, "15m": 96, "1h": 24, "4h": 6}.get(tf, 24)).max()),
            "lo_24h": float(d.low.tail({"5m": 288, "15m": 96, "1h": 24, "4h": 6}.get(tf, 24)).min())}


def analyze(symbol: str, side: str | None = None) -> dict:
    res = {"symbol": symbol, "frames": {}}
    for tf in ("5m", "15m", "1h"):
        res["frames"][tf] = _tf(symbol, tf)
    try:
        res["frames"]["4h"] = _tf_4h(symbol)
    except Exception:
        pass
    try:
        fr = okx._get("/api/v5/public/funding-rate", {"instId": okx.inst(symbol)})[0]
        res["funding_rate_pct"] = round(float(fr["fundingRate"]) * 100, 4)
    except Exception:
        res["funding_rate_pct"] = None
    trends = [f["trend"] for k, f in res["frames"].items() if k in ("15m", "1h", "4h")]
    ups, dns = trends.count("up"), trends.count("down")
    res["bias"] = "aligned_long" if ups >= 2 and dns == 0 else ("aligned_short" if dns >= 2 and ups == 0 else "mixed")
    r5 = res["frames"]["5m"]["rsi"]
    notes = []
    if r5 > 75: notes.append("5m RSI 過熱")
    if r5 < 25: notes.append("5m RSI 超賣")
    if res["funding_rate_pct"] is not None and abs(res["funding_rate_pct"]) > 0.05:
        notes.append(f"資金費率偏極端 {res['funding_rate_pct']}%")
    res["notes"] = notes
    if side:
        want = "aligned_long" if side.lower() in ("long", "buy") else "aligned_short"
        opp = "aligned_short" if want == "aligned_long" else "aligned_long"
        res["verdict"] = "agree" if res["bias"] == want else ("disagree" if res["bias"] == opp else "neutral")
    return res


def _tf_4h(symbol):
    d = okx._frame(okx._get("/api/v5/market/candles", {"instId": okx.inst(symbol), "bar": "4H", "limit": "300"}))
    d = d[d.confirm == 1]
    e20, e50 = ema(d.close, 20), ema(d.close, 50)
    c = d.close.iloc[-1]
    trend = "up" if c > e20.iloc[-1] > e50.iloc[-1] else ("down" if c < e20.iloc[-1] < e50.iloc[-1] else "flat")
    return {"trend": trend, "rsi": round(float(rsi(d.close).iloc[-1]), 1), "atr_pct": round(float(atr(d).iloc[-1] / c * 100), 3), "close": float(c)}
