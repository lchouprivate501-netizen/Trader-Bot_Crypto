#!/usr/bin/env python3
"""Build replay timelines for the AI office console (desk/console) from EA backtest results.

For every run it writes, on one shared bar grid (default 4h):
  OHLC, the long trend EMA and breakout line, the short trend EMA and breakdown line (futures EAs),
  the regime the engine sees (+1 long setup allowed, -1 short setup allowed, 0 neither),
  the chandelier stop while a trade is open (recomputed with the strategy's own formula from
  FreqAI's sigma_day at entry and the highest / lowest price since entry, on 1h candles),
  mark-to-market equity vs buy & hold, and the event list (open, stop moves >= 0.5%, close).

Usage (Freqtrade venv):
  python replay_build.py --run <eth.zip>::ETH --run <sol.zip>::SOL --run <btc.zip>::BTC \
      --datadir user_data/data/binance --models user_data/models --out ../desk/console/replays/demo.json
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ea_lab import sides  # noqa: E402
from mtm_report import build as build_report  # noqa: E402
from mtm_report import equity_curve, load  # noqa: E402
from tv_research import candles_1h, ema, predictions, strategy_params  # noqa: E402

STOP_MOVE_PCT = 0.5  # same threshold as the trading desk's MOVE_STOP


def sig(x: float | None, digits: int = 6) -> float | None:
    return None if x is None or not np.isfinite(x) else float(f"{x:.{digits}g}")


def full_params(p: dict, futures: bool) -> dict:
    p = dict(p)
    if futures:
        for k in ("trend_ema", "ema_band", "slope_h", "breakout_h", "trail_k", "risk_per_trade"):
            if p.get(f"s_{k}") is None:
                p[f"s_{k}"] = p[k]
        if p.get("s_init_k") is None:
            p["s_init_k"] = p["s_trail_k"]
    p["init_k"] = p["trail_k"] if p.get("init_k") is None else p["init_k"]
    p.setdefault("max_stop_pct", 0.30)
    return p


def coin_timeline(zip_path: Path, label: str, datadir: Path, models: Path, bar: str) -> dict:
    strat, _w, market = load(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        cfg = json.loads(zf.read(next(n for n in zf.namelist() if n.endswith("_config.json"))))
    name, pair = strat["_name"], strat["pairlist"][0]
    futures = cfg.get("trading_mode") == "futures"
    p = full_params(strategy_params(name, cfg), futures)
    start = pd.Timestamp(strat["backtest_start"], tz="UTC")
    end = pd.Timestamp(strat["backtest_end"], tz="UTC")

    h = candles_1h(datadir, pair)
    c = h["close"]
    h["ema"] = ema(c, int(p["trend_ema"]))
    h["dh"] = h["high"].rolling(int(p["breakout_h"])).max().shift(1)
    band = float(p["ema_band"])
    slope = int(p.get("slope_h") or 0)
    rising = h["ema"] > h["ema"].shift(slope) if slope > 0 else pd.Series(True, index=h.index)
    risk_on = risk_off = pd.Series(True, index=h.index)
    if int(p.get("ref_trend_ema") or 0) > 0:
        stake = cfg["stake_currency"]
        ref = candles_1h(datadir, f"BTC/{stake}:{stake}" if futures else f"BTC/{stake}")["close"].reindex(h.index).ffill()
        rema = ema(ref, int(p["ref_trend_ema"]))
        risk_on, risk_off = ref > rema * (1 + band), ref < rema * (1 - band)
    long_ok = (c > h["ema"] * (1 + band)) & rising & risk_on
    short_ok = pd.Series(False, index=h.index)
    if futures and p.get("short"):
        h["ema_s"] = ema(c, int(p["s_trend_ema"]))
        h["dl"] = h["low"].rolling(int(p["s_breakout_h"])).min().shift(1)
        sb = float(p["s_ema_band"])
        ss = int(p.get("s_slope_h") or 0)
        falling = h["ema_s"] < h["ema_s"].shift(ss) if ss > 0 else pd.Series(True, index=h.index)
        short_ok = (c < h["ema_s"] * (1 - sb)) & falling & (risk_off if int(p.get("ref_trend_ema") or 0) > 0 else True)
    h["regime"] = np.where(long_ok, 1, np.where(short_ok, -1, 0))

    # FreqAI sigma_day, as in EABase.populate_indicators (hourly sigma forecast, daily-scaled, smoothed)
    rv = np.log(c).diff().rolling(24).std()
    pr = predictions(models, cfg["freqai"]["identifier"], start, int(cfg["freqai"]["backtest_period_days"]))
    ratio = pr["&-vol_ratio"].reindex(h.index).fillna(0.0) if not pr.empty else pd.Series(0.0, index=h.index)
    h["sigma_day"] = (rv * np.exp(ratio) * np.sqrt(24)).ewm(span=72, adjust=False).mean()
    h = h[(h.index >= start) & (h.index < end)].copy()
    h["stop"] = np.nan

    events = []
    for t in sorted(strat["trades"], key=lambda x: x["open_timestamp"]):
        short = bool(t.get("is_short"))
        o = pd.Timestamp(t["open_timestamp"], unit="ms", tz="UTC")
        x = pd.Timestamp(t["close_timestamp"], unit="ms", tz="UTC")
        prev = h.index[h.index < o]
        sd = float(h.loc[prev[-1], "sigma_day"]) if len(prev) else float(h["sigma_day"].dropna().iloc[0])
        k_init, k_trail = (p["s_init_k"], p["s_trail_k"]) if short else (p["init_k"], p["trail_k"])
        op = float(t["open_rate"])
        dist = min(k_init * sd, float(p["max_stop_pct"]))
        seg = h[(h.index >= o.floor("h")) & (h.index <= x)]
        if short:
            init = op * (1 + dist)
            path = np.minimum(init, seg["low"].cummin().clip(upper=op) * (1 + k_trail * sd))
        else:
            init = op * (1 - dist)
            path = np.maximum(init, seg["high"].cummax().clip(lower=op) * (1 - k_trail * sd))
        h.loc[seg.index, "stop"] = path.values
        side = "short" if short else "long"
        events.append({"t": int(o.timestamp()), "type": "open", "side": side, "price": sig(op), "stop": sig(init),
                       "lev": float(t.get("leverage") or 1.0), "tag": t.get("enter_tag"), "sigma": round(100 * sd, 2),
                       "stake": round(float(t["stake_amount"]), 2)})
        last = init
        for ts, s in zip(seg.index, path.values, strict=True):
            if (s < last * (1 - STOP_MOVE_PCT / 100)) if short else (s > last * (1 + STOP_MOVE_PCT / 100)):
                events.append({"t": int(ts.timestamp()), "type": "stop", "side": side, "from": sig(last), "to": sig(s)})
                last = s
        events.append({"t": int(x.timestamp()), "type": "close", "side": side, "price": sig(float(t["close_rate"])),
                       "reason": t["exit_reason"], "pnl": round(float(t["profit_abs"]), 2),
                       "pct": round(100 * float(t["profit_ratio"]), 2), "funding": round(float(t.get("funding_fees") or 0.0), 2)})

    eq, _pos = equity_curve(strat, market)
    h["eq"] = (eq / eq.iloc[0]).reindex(h.index).ffill()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "ema": "last", "dh": "last",
           "regime": "last", "stop": "last", "eq": "last", "sigma_day": "last"}
    for col in ("ema_s", "dl"):
        if col in h:
            agg[col] = "last"
    b = h.resample(bar, label="left", closed="left").agg(agg).dropna(subset=["close"])
    bh = b["close"] / b["close"].iloc[0]

    def col(s, digits=6):
        return [sig(v, digits) for v in s]

    bl = json.loads((HERE.parent / "maintenance" / "baselines.json").read_text()).get(
        f"{pair.split('/')[0].lower()}_perp" if futures else pair.split("/")[0].lower(), {})
    rep = build_report(zip_path, None)
    out = {
        "label": label, "coin": pair.split("/")[0], "pair": pair, "market": "perp" if futures else "spot",
        "strategy": name, "params": {k: p.get(k) for k in ("trend_ema", "ema_band", "breakout_h", "trail_k", "risk_per_trade",
                                                           "s_trend_ema", "s_slope_h", "s_breakout_h", "s_trail_k",
                                                           "ref_trend_ema")},
        "t": [int(ts.timestamp()) for ts in b.index],
        "o": col(b["open"]), "h": col(b["high"]), "l": col(b["low"]), "c": col(b["close"]),
        "ema": col(b["ema"]), "dh": col(b["dh"]), "regime": [int(v) if np.isfinite(v) else 0 for v in b["regime"]],
        "stop": col(b["stop"]), "eq": col(b["eq"], 5), "bh": col(bh, 5), "sigma": col(100 * b["sigma_day"], 3),
        "events": events,
        "guard": {k: bl.get(k) for k in ("dd_1y_p95", "dd_1y_p99", "streak_p95", "streak_p99")},
        "summary": {"return_pct": rep["full"]["strategy"]["total_return_pct"], "max_dd_pct": rep["full"]["strategy"]["max_drawdown_pct"],
                    "bh_return_pct": rep["full"]["buy_hold"].get("total_return_pct"),
                    "bh_max_dd_pct": rep["full"]["buy_hold"].get("max_drawdown_pct"),
                    "trades": len(strat["trades"]), **sides(strat["trades"])},
    }
    for k in ("ema_s", "dl"):
        if k in b:
            out[k] = col(b[k])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", required=True, help="backtest result .zip::label (repeat)")
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--models", default="user_data/models")
    ap.add_argument("--bar", default="4h")
    ap.add_argument("--title", default="EA 回放")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    coins = []
    for spec in a.run:
        z, _, label = spec.partition("::")
        coins.append(coin_timeline(Path(z), label or Path(z).stem, Path(a.datadir), Path(a.models), a.bar))
        print(f"{coins[-1]['label']}: {len(coins[-1]['t'])} bars, {len(coins[-1]['events'])} events")
    doc = {"title": a.title, "bar": a.bar, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "coins": coins}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print(f"wrote {a.out} ({Path(a.out).stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
