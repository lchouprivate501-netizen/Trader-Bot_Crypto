"""Causal helpers for MacdGatedFutures.

MACD matches TradingView ta.ema (pandas ewm span, adjust=False).
All rolling statistics are right-aligned and do not use future bars.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def macd_delta(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    delta = line - sig
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_delta": delta})


def cross_over_zero(delta: pd.Series) -> pd.Series:
    prev = delta.shift(1)
    return (delta > 0) & (prev <= 0)


def cross_under_zero(delta: pd.Series) -> pd.Series:
    prev = delta.shift(1)
    return (delta < 0) & (prev >= 0)


def adx_skill(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX as specified in agiprolabs regime-detection (ewm span=period)."""
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm >= minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm >= plus_dm, 0.0)
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(span=period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False, min_periods=period).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False, min_periods=period).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.ewm(span=period, adjust=False, min_periods=period).mean()


def close_location_buy_pct(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Candle close-location proxy for buy volume share (adaptation of DEX buy_volume_pct)."""
    rng = (high - low).replace(0, np.nan)
    return ((close - low) / rng).fillna(0.5)


def volume_anomaly(volume: pd.Series, lookback: int, mult: float) -> pd.Series:
    baseline = volume.shift(1).rolling(lookback, min_periods=max(10, lookback // 4)).mean()
    return volume > (mult * baseline)


def confirmed_fractals(high: pd.Series, low: pd.Series, n: int = 3) -> tuple[pd.Series, pd.Series]:
    """Right-side confirmed Williams-style fractals.

    A swing at t is confirmed on bar t+n (the right-side bar has closed).
    The confirmation flag is stored on bar t+n, never on t (no lookahead).
    """
    sh = pd.Series(True, index=high.index)
    sl = pd.Series(True, index=low.index)
    for k in range(1, n + 1):
        sh &= high > high.shift(k)
        sh &= high > high.shift(-k)
        sl &= low < low.shift(k)
        sl &= low < low.shift(-k)
    return sh.shift(n).fillna(False), sl.shift(n).fillna(False)


def structure_flags(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 3) -> pd.DataFrame:
    """In-house right-side BOS / CHoCH / HL-LH flags. No smartmoneyconcepts package."""
    sh_conf, sl_conf = confirmed_fractals(high, low, n)
    sh_price = high.shift(n)
    sl_price = low.shift(n)
    last_sh = last_sl = prev_sh = prev_sl = np.nan
    bias = 0
    long_ok = np.zeros(len(close), dtype=bool)
    short_ok = np.zeros(len(close), dtype=bool)
    bias_arr = np.zeros(len(close), dtype=int)
    highs = sh_price.to_numpy()
    lows = sl_price.to_numpy()
    closes = close.to_numpy()
    sh = sh_conf.to_numpy()
    sl = sl_conf.to_numpy()
    for i in range(len(close)):
        if sl[i] and np.isfinite(lows[i]):
            prev_sl, last_sl = last_sl, lows[i]
        if sh[i] and np.isfinite(highs[i]):
            prev_sh, last_sh = last_sh, highs[i]
        if np.isfinite(last_sh) and closes[i] > last_sh:
            bias = 1
        elif np.isfinite(last_sl) and closes[i] < last_sl:
            bias = -1
        hl = np.isfinite(last_sl) and np.isfinite(prev_sl) and last_sl > prev_sl
        lh = np.isfinite(last_sh) and np.isfinite(prev_sh) and last_sh < prev_sh
        long_ok[i] = bias == 1 or hl
        short_ok[i] = bias == -1 or lh
        bias_arr[i] = bias
    return pd.DataFrame(
        {"structure_long_ok": long_ok, "structure_short_ok": short_ok, "structure_bias": bias_arr},
        index=close.index,
    )


def _to_utc_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is None:
        return idx.tz_localize("UTC")
    return idx.tz_convert("UTC")


def last_completed_daily_midnight(last_bar: pd.Timestamp) -> pd.Timestamp:
    """Latest UTC day whose 15m session is complete (bar at or after 23:45 UTC)."""
    t = pd.Timestamp(last_bar)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    day = t.normalize()
    eod = day + pd.Timedelta(hours=23, minutes=45)
    return day if t >= eod else day - pd.Timedelta(days=1)


def pair_slug(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_")


def find_ohlcv_feather(datadir: Path, pair: str, timeframe: str, trading_mode: str = "futures") -> Path | None:
    name = f"{pair_slug(pair)}-{timeframe}-{trading_mode}.feather"
    candidates = [
        Path(datadir) / name,
        Path(datadir) / trading_mode / name,
        Path(datadir) / "futures" / name,
    ]
    # datadir may be user_data/data; also try exchange/futures
    if Path(datadir).name != "futures":
        candidates.extend(Path(datadir).glob(f"**/{name}"))
    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.is_file():
            return c
    return None


def read_daily_close_feather(path: Path) -> pd.Series:
    df = pd.read_feather(path)
    if "date" in df.columns:
        idx = _to_utc_index(pd.DatetimeIndex(pd.to_datetime(df["date"])))
    elif isinstance(df.index, pd.DatetimeIndex):
        idx = _to_utc_index(df.index)
    else:
        raise ValueError(f"no date column in {path}")
    close = pd.to_numeric(df["close"], errors="coerce")
    series = pd.Series(close.to_numpy(), index=idx).sort_index()
    series = series[~series.index.duplicated(keep="last")].dropna()
    series.index = series.index.normalize()
    return series


def daily_from_ohlc_frame(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    df = frame.copy()
    if "date" in df.columns:
        idx = _to_utc_index(pd.DatetimeIndex(pd.to_datetime(df["date"])))
    elif isinstance(df.index, pd.DatetimeIndex):
        idx = _to_utc_index(df.index)
    else:
        return pd.Series(dtype=float)
    series = pd.Series(pd.to_numeric(df["close"], errors="coerce").to_numpy(), index=idx.normalize())
    return series[~series.index.duplicated(keep="last")].sort_index().dropna()


def load_completed_daily_closes(
    pair: str,
    dates_15m: pd.Series,
    close_15m: pd.Series,
    datadir: Path | None = None,
    dp_daily: pd.DataFrame | None = None,
    trading_mode: str = "futures",
) -> pd.Series:
    """Completed daily closes with on-disk 1d as the authoritative history.

    Informative 1d and 15m-resampled days are appended only after the file's
    last date, so a mid-window lookahead slice does not replace official
    daily closes with a different 15m resample. The current incomplete UTC
    day is dropped. Mapping to 15m still uses a next-day known_at (no
    same-day close).
    """
    indexed = pd.Series(
        pd.to_numeric(close_15m, errors="coerce").to_numpy(),
        index=_to_utc_index(pd.DatetimeIndex(pd.to_datetime(dates_15m))),
    ).dropna()
    cutoff = last_completed_daily_midnight(indexed.index.max()) if not indexed.empty else None

    daily = pd.Series(dtype=float)
    if datadir is not None:
        path = find_ohlcv_feather(Path(datadir), pair, "1d", trading_mode)
        if path is not None:
            try:
                daily = read_daily_close_feather(path)
            except Exception as exc:
                logger.warning("failed reading 1d history %s: %s", path, exc)

    extras: list[pd.Series] = []
    from_dp = daily_from_ohlc_frame(dp_daily) if dp_daily is not None else pd.Series(dtype=float)
    if not from_dp.empty:
        extras.append(from_dp)
    if not indexed.empty:
        extras.append(indexed.resample("1D").last().dropna())
    last_file = daily.index.max() if not daily.empty else None
    for extra in extras:
        if last_file is not None:
            extra = extra[extra.index > last_file]
        if not extra.empty:
            daily = pd.concat([daily, extra]).sort_index()
            last_file = daily.index.max()
    if daily.empty:
        return daily
    daily = daily[~daily.index.duplicated(keep="first")].sort_index().dropna()
    daily.index = _to_utc_index(daily.index).normalize()
    if cutoff is not None:
        daily = daily[daily.index <= cutoff]
    return daily


def daily_realized_vol_percentiles(
    close: pd.Series,
    windows_days: list[int],
    dates: pd.Series | None = None,
    daily_close: pd.Series | None = None,
) -> pd.DataFrame:
    """Close-to-close realized vol on completed daily bars, causal percentile rank.

    Prefer a longer `daily_close` series (informative 1d / on-disk history) so
    live dry-run is not limited to the 15m startup window. Percentiles are an
    expanding rank; vol for day D is only mapped onto later 15m bars after a
    1-day shift (no same-day or future close).
    """
    if dates is not None:
        indexed = pd.Series(pd.to_numeric(close, errors="coerce").to_numpy(), index=pd.to_datetime(dates))
    elif not isinstance(close.index, pd.DatetimeIndex):
        raise ValueError("daily_realized_vol_percentiles needs dates or a DatetimeIndex")
    else:
        indexed = close
    indexed.index = _to_utc_index(pd.DatetimeIndex(indexed.index))

    if daily_close is not None and len(daily_close):
        daily = pd.to_numeric(daily_close, errors="coerce")
        daily.index = _to_utc_index(pd.DatetimeIndex(pd.to_datetime(daily.index))).normalize()
        daily = daily[~daily.index.duplicated(keep="last")].sort_index().dropna()
        if not indexed.empty:
            cutoff = last_completed_daily_midnight(indexed.index.max())
            daily = daily[daily.index <= cutoff]
    else:
        daily = indexed.resample("1D").last().dropna()
        if not daily.empty:
            cutoff = last_completed_daily_midnight(indexed.index.max())
            daily = daily[daily.index <= cutoff]

    logret = np.log(daily / daily.shift(1))
    out = pd.DataFrame(index=close.index)
    for w in windows_days:
        vol = logret.rolling(w, min_periods=w).std(ddof=1) * math.sqrt(365)
        pct = vol.expanding(min_periods=max(20, w + 5)).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )
        # Day D's close is known at D+1 00:00 UTC (after the 23:45 bar).
        # merge_asof backward so a 15m bar never sees the same-day or future close,
        # even if `daily` still contains later rows.
        known_at = _to_utc_index(vol.index + pd.Timedelta(days=1)).astype("datetime64[ns, UTC]")
        known = pd.DataFrame(
            {
                "known_at": known_at,
                "vol": vol.to_numpy(),
                "pct": (pct * 100).to_numpy(),
            }
        ).sort_values("known_at")
        left = pd.DataFrame(
            {
                "known_at": _to_utc_index(indexed.index).astype("datetime64[ns, UTC]"),
                "_ord": np.arange(len(indexed)),
            }
        )
        merged = pd.merge_asof(left.sort_values("known_at"), known, on="known_at", direction="backward")
        merged = merged.sort_values("_ord")
        out[f"vol_{w}d"] = merged["vol"].to_numpy()
        out[f"vol_{w}d_pct"] = merged["pct"].to_numpy()
    return out


def btc_trend_from_ohlc(close: pd.Series, ema_len: int = 50, slope_bars: int = 5) -> pd.Series:
    """+1 bull (close>ema and rising ema), -1 bear, 0 neutral."""
    ma = ema(close, ema_len)
    slope = ma.diff(slope_bars)
    trend = pd.Series(0, index=close.index, dtype=int)
    trend[(close > ma) & (slope > 0)] = 1
    trend[(close < ma) & (slope < 0)] = -1
    return trend


def load_gate_file(path: Path, stale_minutes: int, now: datetime) -> dict[str, Any]:
    """Fail-closed reader for user_data/gates/*.json."""
    result = {"ok": False, "reason": "missing", "payload": None}
    if not path.exists():
        return result
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": f"malformed: {exc}", "payload": None}
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "malformed: not an object", "payload": None}
    ts_raw = payload.get("updated_at") or payload.get("as_of") or payload.get("timestamp")
    if not ts_raw:
        return {"ok": False, "reason": "stale_or_missing_timestamp", "payload": payload}
    try:
        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return {"ok": False, "reason": "malformed_timestamp", "payload": payload}
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = now - ts
    if age > timedelta(minutes=stale_minutes) or age < timedelta(minutes=-5):
        return {"ok": False, "reason": f"stale_age={age}", "payload": payload}
    return {"ok": True, "reason": "ok", "payload": payload}


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
