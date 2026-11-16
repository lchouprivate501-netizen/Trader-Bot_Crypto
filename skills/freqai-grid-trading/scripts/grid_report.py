#!/usr/bin/env python3
"""Mark-to-market report for a Freqtrade grid backtest.

Freqtrade's headline drawdown is computed on *closed* trades. A grid session is one long
trade, so that number hides the inventory drawdown in between (and the futures wallet
snapshot does not include unrealised PnL either). This report rebuilds the equity curve
from every filled order (fees included, funding booked when the session closes) and marks
the open position to the hourly close, so it shows the drawdown you would actually have
lived through. The rebuilt final equity is checked against Freqtrade's final balance.

Usage:
  python grid_report.py user_data/backtest_results/backtest-result-....zip \
      --split 2025-01-01 --json out.json --md out.md
  (no path -> newest result in user_data/backtest_results)
"""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


def load(zip_path: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        main = next(n for n in names if n.endswith(".json") and not n.endswith("_config.json"))
        res = json.loads(zf.read(main))
        strat_name = next(iter(res["strategy"]))
        strat = res["strategy"][strat_name]
        wallet_name = next(n for n in names if n.endswith(f"{strat_name}_wallet.feather"))
        wallet = pd.read_feather(io.BytesIO(zf.read(wallet_name)))
        mkt_name = next(n for n in names if n.endswith("_market_change.feather"))
        market = pd.read_feather(io.BytesIO(zf.read(mkt_name)))
    strat["_name"] = strat_name
    return strat, wallet, market


def prices(market: pd.DataFrame) -> pd.Series:
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"], utc=True)
    return m.set_index("date")["mean"].sort_index()


def equity_curve(strat: dict, market: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Hourly mark-to-market equity and signed position (base units), from the orders."""
    px = prices(market)
    events = []  # (timestamp_ms, signed_qty, price, cash_delta)
    for t in strat["trades"]:
        side = -1.0 if t.get("is_short") else 1.0
        for o in t.get("orders", []):
            qty = float(o["amount"])
            price = float(o["safe_price"])
            entry = bool(o["ft_is_entry"])
            signed = qty * (side if entry else -side)
            fee = qty * price * float(t["fee_open"] if entry else t["fee_close"])
            events.append((int(o["order_filled_timestamp"]), signed, price, -signed * price - fee))
        if t.get("funding_fees"):
            events.append((int(t["close_timestamp"]), 0.0, 0.0, float(t["funding_fees"])))
    events.sort(key=lambda e: e[0])
    start = float(strat["starting_balance"])
    candle_ms = int((px.index[1] - px.index[0]).total_seconds() * 1000) if len(px) > 1 else 3_600_000
    cash, pos, i = start, 0.0, 0
    eq, ps = [], []
    for ts, close in px.items():
        end_ms = int(ts.timestamp() * 1000) + candle_ms
        while i < len(events) and events[i][0] < end_ms:
            pos += events[i][1]
            cash += events[i][3]
            i += 1
        eq.append(cash + pos * close)
        ps.append(pos)
    while i < len(events):  # anything after the last candle
        pos += events[i][1]
        cash += events[i][3]
        i += 1
    curve = pd.Series(eq, index=px.index)
    curve.iloc[-1] = cash + pos * px.iloc[-1]
    return curve, pd.Series(ps, index=px.index)


def stats(eq: pd.Series) -> dict:
    if len(eq) < 2:
        return {}
    days = (eq.index[-1] - eq.index[0]).total_seconds() / 86400
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (365.0 / max(days, 1)) - 1
    dd = eq / eq.cummax() - 1
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    sharpe = float(np.sqrt(365) * daily.mean() / daily.std()) if daily.std() > 0 else 0.0
    downside = daily[daily < 0].std()
    sortino = float(np.sqrt(365) * daily.mean() / downside) if downside and downside > 0 else 0.0
    max_dd = float(-dd.min())
    # longest time under water (days)
    under = dd < 0
    longest, start = 0.0, None
    for ts, u in under.items():
        if u and start is None:
            start = ts
        if not u and start is not None:
            longest = max(longest, (ts - start).total_seconds() / 86400)
            start = None
    if start is not None:
        longest = max(longest, (eq.index[-1] - start).total_seconds() / 86400)
    return {
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "days": round(days, 1),
        "total_return_pct": round(100 * total, 2),
        "cagr_pct": round(100 * cagr, 2),
        "max_drawdown_pct": round(100 * max_dd, 2),
        "calmar": round(cagr / max_dd, 2) if max_dd > 0 else None,
        "sharpe_daily": round(sharpe, 2),
        "sortino_daily": round(sortino, 2),
        "longest_underwater_days": round(longest, 1),
    }


def bh_stats(market: pd.DataFrame, start, end) -> dict:
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"], utc=True)
    m = m.set_index("date")["mean"]
    m = m[(m.index >= start) & (m.index <= end)]
    return stats(m / m.iloc[0] * 1.0) if len(m) > 1 else {}


def order_stats(trades: list[dict], start=None, end=None) -> dict:
    tags: dict[str, int] = {}
    volume = 0.0
    for t in trades:
        for o in t.get("orders", []):
            ts = pd.Timestamp(o["order_filled_timestamp"], unit="ms", tz="UTC")
            if (start is not None and ts < start) or (end is not None and ts >= end):
                continue
            tags[o.get("ft_order_tag") or "?"] = tags.get(o.get("ft_order_tag") or "?", 0) + 1
            volume += float(o.get("cost") or 0.0)
    exits: dict[str, int] = {}
    sessions = 0
    for t in trades:
        ts = pd.Timestamp(t["open_timestamp"], unit="ms", tz="UTC")
        if (start is not None and ts < start) or (end is not None and ts >= end):
            continue
        sessions += 1
        exits[t["exit_reason"]] = exits.get(t["exit_reason"], 0) + 1
    return {
        "sessions": sessions,
        "grid_buys": tags.get("grid_buy", 0),
        "grid_sells": tags.get("grid_sell", 0),
        "order_volume_quote": round(volume, 2),
        "exit_reasons": exits,
    }


def yearly(eq: pd.Series, market: pd.DataFrame) -> list[dict]:
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"], utc=True)
    m = m.set_index("date")["mean"]
    out = []
    for y in sorted(set(eq.index.year)):
        e = eq[eq.index.year == y]
        mm = m[m.index.year == y]
        if len(e) < 24:
            continue
        dd = (e / e.cummax() - 1).min()
        out.append(
            {
                "year": int(y),
                "strategy_pct": round(100 * (e.iloc[-1] / e.iloc[0] - 1), 2),
                "strategy_maxdd_pct": round(-100 * dd, 2),
                "buy_hold_pct": round(100 * (mm.iloc[-1] / mm.iloc[0] - 1), 2) if len(mm) > 1 else None,
                "buy_hold_maxdd_pct": round(-100 * (mm / mm.cummax() - 1).min(), 2) if len(mm) > 1 else None,
            }
        )
    return out


def exposure(pos: pd.Series, eq: pd.Series, market: pd.DataFrame) -> dict:
    px = prices(market).reindex(pos.index)
    gross = (pos.abs() * px / eq).fillna(0.0)
    return {
        "time_in_market_pct": round(100 * float((pos.abs() > 1e-12).mean()), 1),
        "time_long_pct": round(100 * float((pos > 1e-12).mean()), 1),
        "time_short_pct": round(100 * float((pos < -1e-12).mean()), 1),
        "avg_gross_exposure_pct": round(100 * float(gross.mean()), 1),
        "max_gross_exposure_pct": round(100 * float(gross.max()), 1),
    }


def build(zip_path: Path, split: str | None) -> dict:
    strat, wallet, market = load(zip_path)
    eq, pos = equity_curve(strat, market)
    rep = {
        "strategy": strat["_name"],
        "result_file": zip_path.name,
        "timerange": strat.get("timerange"),
        "trading_mode": strat.get("trading_mode"),
        "freqai_identifier": strat.get("freqai_identifier"),
        "starting_balance": strat.get("starting_balance"),
        "final_balance": round(float(strat.get("final_balance", 0)), 2),
        "rebuilt_final_equity": round(float(eq.iloc[-1]), 2),
        "full": {
            "strategy": stats(eq),
            "buy_hold": bh_stats(market, eq.index[0], eq.index[-1]),
            "orders": order_stats(strat["trades"]),
            "exposure": exposure(pos, eq, market),
        },
        "yearly": yearly(eq, market),
    }
    if split:
        cut = pd.Timestamp(split, tz="UTC")
        for name, part, lo, hi in (
            ("in_sample", eq[eq.index < cut], None, cut),
            ("out_of_sample", eq[eq.index >= cut], cut, None),
        ):
            if len(part) > 24:
                rep[name] = {
                    "strategy": stats(part),
                    "buy_hold": bh_stats(market, part.index[0], part.index[-1]),
                    "orders": order_stats(strat["trades"], lo, hi),
                }
    return rep


def to_md(rep: dict) -> str:
    lines = [f"### {rep['strategy']} ({rep['trading_mode']}, {rep['timerange']})", ""]
    lines.append("| Segment | Return | CAGR | Max DD (MTM) | Calmar | Sharpe | B&H return | B&H max DD | Grid buys/sells | Sessions |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for seg in ("full", "in_sample", "out_of_sample"):
        if seg not in rep:
            continue
        s, b, o = rep[seg]["strategy"], rep[seg]["buy_hold"], rep[seg]["orders"]
        lines.append(
            f"| {seg} {s['start']}→{s['end']} | {s['total_return_pct']}% | {s['cagr_pct']}% | "
            f"{s['max_drawdown_pct']}% | {s['calmar']} | {s['sharpe_daily']} | "
            f"{b.get('total_return_pct')}% | {b.get('max_drawdown_pct')}% | "
            f"{o['grid_buys']}/{o['grid_sells']} | {o['sessions']} |"
        )
    lines += ["", "| Year | Strategy | Strategy max DD | Buy & hold | B&H max DD |", "|---|---|---|---|---|"]
    for y in rep["yearly"]:
        lines.append(
            f"| {y['year']} | {y['strategy_pct']}% | {y['strategy_maxdd_pct']}% | "
            f"{y['buy_hold_pct']}% | {y['buy_hold_maxdd_pct']}% |"
        )
    ex = rep["full"]["orders"]["exit_reasons"]
    xp = rep["full"]["exposure"]
    lines += [
        "",
        f"Exit reasons: {ex}.",
        f"Exposure: in market {xp['time_in_market_pct']}% of hours (long {xp['time_long_pct']}%, "
        f"short {xp['time_short_pct']}%), average gross exposure {xp['avg_gross_exposure_pct']}% of "
        f"equity, max {xp['max_gross_exposure_pct']}%.",
        f"Final equity rebuilt from orders {rep['rebuilt_final_equity']} vs Freqtrade final balance "
        f"{rep['final_balance']} (start {rep['starting_balance']}).",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result", nargs="?", help="backtest result .zip (default: newest)")
    ap.add_argument("--results-dir", default="user_data/backtest_results")
    ap.add_argument("--split", help="in-sample / out-of-sample boundary, e.g. 2025-01-01")
    ap.add_argument("--json", help="write the report as JSON")
    ap.add_argument("--md", help="write the report as Markdown")
    args = ap.parse_args()
    path = Path(args.result) if args.result else max(Path(args.results_dir).glob("*.zip"), key=lambda p: p.stat().st_mtime)
    rep = build(path, args.split)
    md = to_md(rep)
    print(md)
    if args.json:
        Path(args.json).write_text(json.dumps(rep, indent=2))
    if args.md:
        Path(args.md).write_text(md)


if __name__ == "__main__":
    main()
