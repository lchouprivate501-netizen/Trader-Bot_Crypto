#!/usr/bin/env python3
"""EA lab: backtest, tune (development period only) and validate the BTC / ETH / SOL EAs.

  python ea_lab.py backtest --coin btc [--timerange 20210601-20241212] [--params '{...}']
  python ea_lab.py tune     --coin btc --grid '{"trail_k":[2.5,3,3.5]}'   # dev period only
  python ea_lab.py validate --coin btc        # pre-registered V1-V4, run once, PASS/FAIL

Reuses the freqai-grid-trading skill's backtest wrapper (ft_offline.py) and mark-to-market
report (grid_report.py). Run with the Freqtrade venv's python. FT_OFFLINE=1 for sandboxes
without exchange API access. Thresholds and periods: references/validation-protocol.md.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
GRID_SCRIPTS = SKILL.parent / "freqai-grid-trading" / "scripts"
sys.path.insert(0, str(GRID_SCRIPTS))
from grid_report import build, load  # noqa: E402

DEV = "20210601-20241212"
V1 = "20180601-20210601"
V2 = "20241212-20261101"
V3 = "20210901-20261101"
V3_PAIRS = ["AVAX/USDT", "NEAR/USDT", "DOT/USDT", "ADA/USDT", "LINK/USDT", "DOGE/USDT"]
FEE = 0.001
TUNED = {"btc": ["breakout_h", "trail_k", "risk_per_trade"], "eth": ["breakout_h", "trail_k", "risk_per_trade"],
         "sol": ["breakout_h", "trail_k", "risk_per_trade"]}


def run(coin: str, timerange: str, params: dict | None = None, pair: str | None = None,
        fee: float = FEE, userdir: str = "user_data", keep: str | None = None,
        n_jobs: int = 1) -> dict:
    """One Freqtrade backtest; returns the MTM report plus trade statistics."""
    with tempfile.TemporaryDirectory() as tmp:
        override: dict = {"freqai": {"model_training_parameters": {"n_jobs": n_jobs}}}
        if params:
            override["ea_params"] = params
        if pair:
            override["exchange"] = {"pair_whitelist": [pair]}
        ov = Path(tmp) / "override.json"
        ov.write_text(json.dumps(override))
        out = Path(keep) if keep else Path(tmp) / "results"
        out.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "FT_OFFLINE": os.environ.get("FT_OFFLINE", "0"), "FT_FAST": "1"}
        cmd = [sys.executable, str(GRID_SCRIPTS / "ft_offline.py"), "backtesting",
               "-c", str(SKILL / "user_data/configs" / f"config_{coin}_ea.json"), "-c", str(ov),
               "--userdir", userdir,
               "--strategy-path", str(SKILL / "user_data/strategies"),
               "--freqaimodel-path", str(SKILL / "user_data/freqaimodels"),
               "--timerange", timerange, "--fee", str(fee), "--cache", "none",
               "--backtest-directory", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        zips = sorted(out.glob("*.zip"), key=lambda p: p.stat().st_mtime)
        if proc.returncode != 0 or not zips:
            return {"error": (proc.stderr or proc.stdout)[-3000:], "params": params, "pair": pair}
        rep = summarize(zips[-1])
        rep.update({"params": params or {}, "pair": pair, "timerange": timerange, "fee": fee,
                    "result_file": str(zips[-1]) if keep else None})
        return rep


def summarize(zip_path: Path) -> dict:
    strat, _w, _m = load(zip_path)
    rep = build(zip_path, None)
    pnl = [float(t["profit_abs"]) for t in strat["trades"]]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x <= 0]
    exits: dict[str, int] = {}
    for t in strat["trades"]:
        exits[t["exit_reason"]] = exits.get(t["exit_reason"], 0) + 1
    hold = [t["trade_duration"] / 60 / 24 for t in strat["trades"]]
    s, b = rep["full"]["strategy"], rep["full"]["buy_hold"]
    return {
        "strategy": strat["_name"],
        "pair_traded": strat["pairlist"][0],
        "return_pct": s["total_return_pct"], "cagr_pct": s["cagr_pct"],
        "max_dd_pct": s["max_drawdown_pct"], "calmar": s["calmar"], "sharpe": s["sharpe_daily"],
        "bh_return_pct": b.get("total_return_pct"), "bh_max_dd_pct": b.get("max_drawdown_pct"),
        "trades": len(pnl), "win_rate_pct": round(100 * len(wins) / len(pnl), 1) if pnl else 0.0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "avg_hold_days": round(sum(hold) / len(hold), 1) if hold else 0.0,
        "exit_reasons": exits,
        "exposure": rep["full"]["exposure"],
        "yearly": rep["yearly"],
    }


def fmt(r: dict, keys: list[str] | None = None) -> str:
    if "error" in r:
        return f"ERROR {r.get('pair') or ''} {r.get('params')}: {r['error'][-300:]}"
    head = json.dumps({k: r["params"][k] for k in keys}) if keys else (r.get("pair_traded") or "")
    return (f"{head:46s} ret {r['return_pct']:8.1f}%  cagr {r['cagr_pct']:6.1f}%  mdd {r['max_dd_pct']:5.1f}%  "
            f"calmar {str(r['calmar']):>5s}  PF {str(r['profit_factor']):>5s}  n {r['trades']:3d}  "
            f"win {r['win_rate_pct']:4.1f}%  B&H {r['bh_return_pct']}% / dd {r['bh_max_dd_pct']}%")


def _job(args: tuple) -> dict:
    return run(*args)


def aligned(timerange: str, period_days: int = 30) -> bool:
    a, b = (datetime.strptime(x, "%Y%m%d") for x in timerange.split("-"))
    return (b - a).days % period_days == 0


def cmd_tune(a) -> None:
    if not aligned(a.timerange):
        sys.exit(f"{a.timerange}: end must be start + k*30 days (FreqAI window cache)")
    grid = json.loads(a.grid)
    fixed = json.loads(a.fixed)
    keys = list(grid)
    combos = [{**fixed, **dict(zip(keys, v, strict=True))} for v in itertools.product(*grid.values())]
    jobs = [(a.coin, a.timerange, c, None, a.fee, a.userdir) for c in combos]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        rows = list(pool.map(_job, jobs))
    ok = sorted([r for r in rows if "error" not in r], key=lambda r: r["calmar"] or -9, reverse=True)
    for r in ok:
        print(fmt(r, keys))
    for r in rows:
        if "error" in r:
            print(fmt(r), file=sys.stderr)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=2))


def cmd_backtest(a) -> None:
    r = run(a.coin, a.timerange, json.loads(a.params) if a.params else None, a.pair, a.fee,
            a.userdir, a.keep, n_jobs=a.n_jobs)
    print(fmt(r) if "error" in r else json.dumps(r, indent=2))


def criteria(coin: str, res: dict) -> list[tuple[str, bool, str]]:
    out = []
    v2, v4 = res["V2"], res["V4"]
    if coin in ("btc", "eth"):
        v1 = res["V1"]
        out.append(("V1 總報酬 > 0", v1["return_pct"] > 0, f"{v1['return_pct']}%"))
        out.append(("V1 最大回撤 < 持有最大回撤的 50%", v1["max_dd_pct"] < 0.5 * v1["bh_max_dd_pct"],
                    f"{v1['max_dd_pct']}% vs 持有 {v1['bh_max_dd_pct']}%"))
        out.append(("V1 獲利因子 ≥ 1.3 且交易 ≥ 15 筆",
                    (v1["profit_factor"] or 0) >= 1.3 and v1["trades"] >= 15,
                    f"PF {v1['profit_factor']}，{v1['trades']} 筆"))
    else:
        v3 = res["V3"]
        prof = sum(1 for r in v3 if r["return_pct"] > 0)
        avg_ret = sum(r["return_pct"] for r in v3) / len(v3)
        avg_dd = sum(r["max_dd_pct"] for r in v3) / len(v3)
        avg_bh_dd = sum(r["bh_max_dd_pct"] for r in v3) / len(v3)
        out.append(("V3 6 幣中 ≥ 4 個獲利且平均報酬 > 0", prof >= 4 and avg_ret > 0,
                    f"{prof}/6 獲利，平均 {avg_ret:.1f}%"))
        out.append(("V3 平均最大回撤 < 持有平均最大回撤的 50%", avg_dd < 0.5 * avg_bh_dd,
                    f"{avg_dd:.1f}% vs 持有 {avg_bh_dd:.1f}%"))
        dev = res["DEV"]
        out.append(("研發期獲利因子 ≥ 1.3", (dev["profit_factor"] or 0) >= 1.3, f"PF {dev['profit_factor']}"))
    out.append(("V2 報酬 > 持有且最大回撤 ≤ 30%",
                v2["return_pct"] > v2["bh_return_pct"] and v2["max_dd_pct"] <= 30,
                f"{v2['return_pct']}% vs 持有 {v2['bh_return_pct']}%，回撤 {v2['max_dd_pct']}%"))
    perturb = v4["perturbations"]
    share = sum(1 for r in perturb if r["return_pct"] > 0) / len(perturb)
    out.append(("V4 ≥ 75% 參數擾動仍獲利，且 0.20% 手續費仍獲利",
                share >= 0.75 and v4["fee_0.2pct"]["return_pct"] > 0,
                f"{share:.0%} 擾動獲利；0.20% 手續費 {v4['fee_0.2pct']['return_pct']}%"))
    return out


def cmd_validate(a) -> None:
    coin = a.coin
    import importlib

    sys.path.insert(0, str(SKILL / "user_data/strategies"))
    cfg = json.loads((SKILL / "user_data/configs" / f"config_{coin}_ea.json").read_text())
    cls = getattr(importlib.import_module(cfg["strategy"]), cfg["strategy"])
    base = {**cls.EA, **cfg.get("ea_params", {})}
    keep = Path(a.keep) / coin
    res: dict = {"coin": coin, "frozen_params": base, "ran_at": datetime.utcnow().isoformat() + "Z"}

    singles = [("DEV", DEV, None, None), ("V2", V2, None, None)]
    if coin in ("btc", "eth"):
        singles.append(("V1", V1, None, None))
    jobs = [(coin, tr, None, pair, FEE, a.userdir, str(keep / name), 1) for name, tr, _p, pair in singles]
    if coin == "sol":
        jobs += [(coin, V3, None, p, FEE, a.userdir, str(keep / f"V3_{p.split('/')[0]}"), 1) for p in V3_PAIRS]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        outs = list(pool.map(_job, jobs))
    names = [s[0] for s in singles] + ([f"V3_{p.split('/')[0]}" for p in V3_PAIRS] if coin == "sol" else [])
    for name, r in zip(names, outs, strict=True):
        if "error" in r:
            sys.exit(f"{name} failed: {r['error'][-1500:]}")
        res[name] = r
    if coin == "sol":
        res["V3"] = [res.pop(f"V3_{p.split('/')[0]}") for p in V3_PAIRS]

    # V4: robustness inside the development period (cached FreqAI windows)
    pert = []
    for k in TUNED[coin]:
        for f in (0.75, 1.25):
            v = base[k] * f
            pert.append({k: int(round(v)) if isinstance(base[k], int) else round(v, 4)})
    jobs = [(coin, DEV, p, None, FEE, a.userdir) for p in pert] + [(coin, DEV, None, None, 0.002, a.userdir)]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        outs = list(pool.map(_job, jobs))
    for r in outs:
        if "error" in r:
            sys.exit(f"V4 failed: {r['error'][-1500:]}")
    res["V4"] = {"perturbations": outs[:-1], "fee_0.2pct": outs[-1]}

    res["criteria"] = [{"test": t, "pass": bool(ok), "value": v} for t, ok, v in criteria(coin, res)]
    res["verdict"] = "PASS" if all(c["pass"] for c in res["criteria"]) else "FAIL"
    Path(a.out or f"validation_{coin}.json").write_text(json.dumps(res, indent=2, default=str))
    for c in res["criteria"]:
        print(("PASS " if c["pass"] else "FAIL ") + c["test"] + "  ->  " + c["value"])
    print("VERDICT", coin.upper(), res["verdict"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("backtest", "tune", "validate"):
        s = sub.add_parser(name)
        s.add_argument("--coin", required=True, choices=["btc", "eth", "sol"])
        s.add_argument("--userdir", default=os.environ.get("FT_HOME", "user_data"))
        s.add_argument("--fee", type=float, default=FEE)
        s.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
        s.add_argument("--out")
        if name == "backtest":
            s.add_argument("--timerange", default=DEV)
            s.add_argument("--params")
            s.add_argument("--pair")
            s.add_argument("--keep", help="directory to keep the result zip in")
            s.add_argument("--n-jobs", type=int, default=4, help="LightGBM threads")
        if name == "tune":
            s.add_argument("--timerange", default=DEV)
            s.add_argument("--grid", required=True)
            s.add_argument("--fixed", default="{}")
        if name == "validate":
            s.add_argument("--keep", default="ea_validation", help="where result zips are kept")
    a = ap.parse_args()
    {"backtest": cmd_backtest, "tune": cmd_tune, "validate": cmd_validate}[a.cmd](a)


if __name__ == "__main__":
    main()
