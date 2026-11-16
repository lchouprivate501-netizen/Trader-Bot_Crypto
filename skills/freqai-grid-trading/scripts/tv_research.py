#!/usr/bin/env python3
"""Build TradingView Lightweight Charts research pages from grid backtests.

One self-contained HTML page per run, one tab per backtest result:
  pane 1  candles, the strategy's trend EMA, in-market sessions (shaded by result),
          every grid buy / sell at its fill price, session entries / exits with reason,
          and (when the strategy uses it) the BTC risk-on strip
  pane 2  mark-to-market equity vs buy & hold (both start at 1.0)
  pane 3  drawdown of both
  pane 4  FreqAI: predicted daily sigma vs the sigma that actually followed, grid step
  pane 5  FreqAI drift z-score and the strategy's enter / exit thresholds

TradingView Lightweight Charts (Apache-2.0, https://github.com/tradingview/lightweight-charts)
is installed by `npm install` in ../tradingview; by default it is inlined so the page works
offline. --cdn loads the same pinned version from jsDelivr instead.

Usage (Freqtrade venv):
  python tv_research.py \
      --run user_data/backtest_results/<btc>.zip::BTC --run <eth>.zip::ETH --run <sol>.zip::SOL \
      --datadir user_data/data/binance --models user_data/models \
      --split 2024-12-12 --notes notes.json --out research.html
"""

from __future__ import annotations

import argparse
import html
import importlib
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TV_DIR = SKILL / "tradingview"
LIB_VERSION = "5.2.1"
LIB_FILE = TV_DIR / "node_modules/lightweight-charts/dist/lightweight-charts.standalone.production.js"
CDN = f"https://cdn.jsdelivr.net/npm/lightweight-charts@{LIB_VERSION}/dist/lightweight-charts.standalone.production.js"

sys.path.insert(0, str(HERE))
from grid_report import build as build_report  # noqa: E402
from grid_report import equity_curve, load  # noqa: E402


STRATEGY_PATHS = [SKILL / "user_data/strategies"]


def strategy_params(name: str, cfg: dict) -> dict:
    """Grid strategies keep their parameters in GRID, EA strategies in EA."""
    for path in STRATEGY_PATHS:
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    cls = getattr(importlib.import_module(name), name)
    base = getattr(cls, "GRID", None) or getattr(cls, "EA", {})
    return {**base, **cfg.get("grid_params", {}), **cfg.get("ea_params", {})}


def candles_1h(datadir: Path, pair: str) -> pd.DataFrame:
    base, rest = pair.split("/")
    if ":" in rest:
        f = datadir / "futures" / f"{base}_{rest.replace(':', '_')}-1h-futures.feather"
    else:
        f = datadir / f"{base}_{rest}-1h.feather"
    return pd.read_feather(f).set_index("date").sort_index()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def predictions(models: Path, identifier: str, start: pd.Timestamp, period_days: int) -> pd.DataFrame:
    files = sorted((models / identifier / "backtesting_predictions").glob("*_prediction.feather"))
    keep = []
    for f in files:  # only windows anchored at this run's start (other runs may share the folder)
        ts = int(f.name.split("_")[2])
        if (ts - int(start.timestamp())) % (period_days * 86400) == 0:
            keep.append(pd.read_feather(f))
    if not keep:
        return pd.DataFrame()
    return pd.concat(keep).drop_duplicates("date").set_index("date").sort_index()


def secs(ix) -> list[int]:
    return [int(t.timestamp()) for t in ix]


def rnd(x: float, n: int = 6) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), n)


def coin_payload(zip_path: Path, datadir: Path, models: Path, bar: str, split: str | None,
                 label: str | None = None) -> dict:
    strat, _wallet, market = load(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        cfg_name = next(n for n in zf.namelist() if n.endswith("_config.json"))
        cfg = json.loads(zf.read(cfg_name))
    name = strat["_name"]
    pair = strat["pairlist"][0]
    p = strategy_params(name, cfg)
    start = pd.Timestamp(strat["backtest_start"], tz="UTC")
    end = pd.Timestamp(strat["backtest_end"], tz="UTC")

    h = candles_1h(datadir, pair)
    close = h["close"]
    ema_slow = ema(close, int(p["trend_ema"]))
    logc = np.log(close)
    rv = logc.diff().rolling(24).std()
    h = h.assign(ema=ema_slow, rv=rv, fwd_rv=rv.shift(-24))
    if int(p.get("ref_trend_ema", 0)) > 0:  # BTC risk-on filter (ETH)
        stake = cfg["stake_currency"]
        ref_pair = f"BTC/{stake}:{stake}" if cfg.get("trading_mode") == "futures" else f"BTC/{stake}"
        ref = candles_1h(datadir, ref_pair)["close"].reindex(h.index).ffill()
        h["risk_on"] = ref > ema(ref, int(p["ref_trend_ema"])) * (1 + float(p["ema_band"]))
    h = h[(h.index >= start) & (h.index < end)]

    pr = predictions(models, cfg["freqai"]["identifier"], start, int(cfg["freqai"]["backtest_period_days"]))
    if not pr.empty:
        pr = pr.reindex(h.index)
        sigma = h["rv"] * np.exp(pr["&-vol_ratio"])
        z = (pr["&-drift"] - pr["&-drift_mean"]) / pr["&-drift_std"]
        h = h.assign(sigma_pred=sigma * np.sqrt(24) * 100, sigma_real=h["fwd_rv"] * np.sqrt(24) * 100, z=z)
        if "step_mult" in p:  # grid strategies: the grid step
            h["step"] = (p["step_mult"] * sigma).clip(p["step_min"], p["step_max"]) * 100
        elif "trail_k" in p:  # EAs: the chandelier stop distance
            h["step"] = p["trail_k"] * (sigma * np.sqrt(24)).ewm(span=72, adjust=False).mean() * 100
    if int(p.get("breakout_h", 0)) > 0:
        h["donchian"] = h["high"].rolling(int(p["breakout_h"])).max().shift(1)

    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "ema": "last"}
    if "donchian" in h:
        agg["donchian"] = "last"
    for col, how in (("sigma_pred", "mean"), ("sigma_real", "mean"), ("step", "mean"), ("z", "last"), ("risk_on", "last")):
        if col in h:
            agg[col] = how
    b = h.resample(bar, label="left", closed="left").agg(agg).dropna(subset=["close"])
    t = secs(b.index)

    eq, pos = equity_curve(strat, market)
    eq = (eq / eq.iloc[0]).resample(bar, label="left", closed="left").last().reindex(b.index).ffill()
    bh = (b["close"] / b["close"].iloc[0])
    dd_eq = eq / eq.cummax() - 1
    dd_bh = bh / bh.cummax() - 1

    sessions, fills = [], []
    for tr in strat["trades"]:
        o = int(tr["open_timestamp"] // 1000)
        c = int(tr["close_timestamp"] // 1000)
        sessions.append(
            {
                "o": o,
                "c": c,
                "pnl": rnd(tr["profit_abs"], 2),
                "pct": rnd(100 * tr["profit_ratio"], 2),
                "exit": tr["exit_reason"],
                "short": bool(tr.get("is_short")),
                "op": rnd(tr["open_rate"], 6),
                "cp": rnd(tr["close_rate"], 6),
            }
        )
        for od in tr.get("orders", []):
            tag = od.get("ft_order_tag")
            if tag in ("grid_buy", "grid_sell"):
                px = float(od["safe_price"])
                fills.append([int(od["order_filled_timestamp"] // 1000), float(f"{px:.6g}"), 1 if tag == "grid_buy" else 0])

    def col(values, nd: int) -> list:  # aligned to "t"; None where missing
        return [rnd(v, nd) if v is not None and np.isfinite(v) else None for v in values]

    def sig(values, digits: int = 6) -> list:  # significant-digit rounding for prices
        return [float(f"{v:.{digits}g}") if np.isfinite(v) else None for v in values]

    rep = build_report(zip_path, split)
    out = {
        "id": name,
        "coin": pair.split("/")[0],
        "label": label or pair.split("/")[0],
        "pair": pair,
        "mode": strat.get("trading_mode"),
        "params": {k: p.get(k) for k in ("trend_ema", "ema_band", "core_frac", "max_lots", "step_mult", "enter_z", "exit_z",
                                          "ref_trend_ema", "trail_steps", "break_steps", "breakout_h", "trail_k", "vol_target")},
        "kind": "grid" if "step_mult" in p else "ea",
        "t": t,
        "o": sig(b["open"]), "h": sig(b["high"]), "l": sig(b["low"]), "c": sig(b["close"]),
        "ema": sig(b["ema"]),
        "equity": col(eq, 4),
        "bh": col(bh, 4),
        "dd_eq": col(100 * dd_eq, 1),
        "dd_bh": col(100 * dd_bh, 1),
        "sessions": sessions,
        "fills": fills,
        "report": {k: rep[k] for k in ("full", "in_sample", "out_of_sample", "yearly") if k in rep},
        "split": int(pd.Timestamp(split, tz="UTC").timestamp()) if split else None,
    }
    if "donchian" in b:
        out["donchian"] = sig(b["donchian"])
    if out["kind"] == "ea":  # EAs do not use the drift forecast
        b = b.drop(columns=["z"], errors="ignore")
    for name_, nd in (("sigma_pred", 2), ("sigma_real", 2), ("step", 2), ("z", 2)):
        if name_ in b:
            out[name_] = col(b[name_], nd)
    if "risk_on" in b:
        out["risk_on"] = [1 if v is True or v == 1 else 0 for v in b["risk_on"]]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="append", required=True,
                    help="backtest result .zip, optionally zip::label (repeat per tab)")
    ap.add_argument("--datadir", default="user_data/data/binance")
    ap.add_argument("--models", default="user_data/models")
    ap.add_argument("--bar", default="4h", help="chart bar size (resampled from 1h)")
    ap.add_argument("--split", default="2024-12-12", help="in-sample / out-of-sample boundary")
    ap.add_argument("--notes", help="JSON list of research notes {coin,title,from,to,body}")
    ap.add_argument("--strategy-path", action="append", default=[],
                    help="extra strategy folder(s) to import from (e.g. the EA skill)")
    ap.add_argument("--out", default="grid_research.html")
    ap.add_argument("--cdn", action="store_true", help="load Lightweight Charts from jsDelivr instead of inlining")
    ap.add_argument("--fragment", action="store_true", help="omit <html>/<head>/<body> (for hosts that add them)")
    ap.add_argument("--title", default="FreqAI 網格研究圖表")
    ap.add_argument("--subtitle", default="BTC、ETH、SOL 三個現貨網格在 2021-06 → 2026-10 的完整回測，每一筆網格成交都畫在成交價上。"
                    "陰影是持倉期間（綠 = 該輪獲利、紅 = 虧損），淡藍底是樣本外。")
    args = ap.parse_args()

    STRATEGY_PATHS.extend(Path(x) for x in args.strategy_path)
    coins = []
    for spec in args.run:
        z, _, label = spec.partition("::")
        coins.append(coin_payload(Path(z), Path(args.datadir), Path(args.models), args.bar, args.split, label or None))
    notes = json.loads(Path(args.notes).read_text()) if args.notes else []
    data = json.dumps({"coins": coins, "notes": notes, "lib": LIB_VERSION}, separators=(",", ":"))
    tpl = (TV_DIR / "template.html").read_text()
    if args.cdn:
        lib = f'<script src="{CDN}"></script>'
    else:
        if not LIB_FILE.exists():
            sys.exit(f"{LIB_FILE} missing: run `npm install` in {TV_DIR} (or pass --cdn)")
        lib = "<script>\n" + LIB_FILE.read_text() + "\n</script>"
    page = tpl.replace("__PAGE_TITLE__", html.escape(args.title)).replace("__PAGE_SUB__", html.escape(args.subtitle))
    page = page.replace("<!--__LIB__-->", lib).replace("/*__DATA__*/null", data.replace("</", "<\\/"))
    if not args.fragment:
        page = (
            '<!doctype html>\n<html lang="zh-Hant">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            "</head>\n<body>\n" + page + "\n</body>\n</html>\n"
        )
    Path(args.out).write_text(page)
    print(f"wrote {args.out} ({len(page) / 1e6:.1f} MB, {len(coins)} strategies)")


if __name__ == "__main__":
    main()
