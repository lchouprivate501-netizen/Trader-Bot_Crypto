"""研發部流水線：寫好的策略 → 70/30 切分 → 樣本內優化 → nautilus 回測（樣本內 + 樣本外）→ 報表 → 登記簿。
用法: python -m rnd.pipeline <strategy> [--trials 60] [--no-opt]
樣本外資料只在最後評分一次，絕不回頭調參。"""
from __future__ import annotations
import argparse, json, time
from datetime import datetime, timezone
import pandas as pd
import nautilus_trader

from company.paths import REPORTS, criteria, universe, write_json
from rnd import data, engine, registry, report
from rnd.optimize import optimize
from rnd.strategies import get
from rnd.strategies.base import attach_htf


def load_frames(symbols):
    frames = {}
    for s in symbols:
        try:
            d5 = data.load(s, "5m")
        except FileNotFoundError:
            continue
        frames[s] = attach_htf(d5, data.load(s, "1h"))
    return frames


def run(name: str, trials: int = 60, optimize_on: bool = True, log=print) -> dict:
    mod = get(name)
    c = criteria()
    fee = c["taker_fee"]
    syms = universe()["backtest_symbols"]
    frames = load_frames(syms)
    if not frames:
        raise RuntimeError("no data; run python -m rnd.data first")
    t0 = min(f.ts.iloc[0] for f in frames.values()); t1 = max(f.ts.iloc[-1] for f in frames.values())
    split = t0 + (t1 - t0) * (1 - c["oos_fraction"])
    is_f = {s: f[f.ts < split].reset_index(drop=True) for s, f in frames.items()}
    registry.set_status(name, "coded", description=mod.DESCRIPTION, module=f"rnd/strategies/{name}.py")
    log(f"[{name}] data {t0} → {t1}; split {split}; pairs {list(frames)}")
    if optimize_on and trials > 0:
        t = time.time()
        opt = optimize(mod, is_f, fee, trials, min_trades=int(c["min_trades"] * 0.7 / 0.3 * 0.5))
        log(f"[{name}] optimized in {time.time()-t:.0f}s: {opt}")
        params = opt["params"]
    else:
        opt, params = {"trials": 0}, dict(mod.DEFAULTS)
    max_hold = int(params.get("max_hold", 36))
    sig_full = {s: mod.signals(f, params) for s, f in frames.items()}
    res = {}
    for label, mask in (("is", lambda f: f.ts < split), ("oos", lambda f: f.ts >= split)):
        fr = {s: f[mask(f)].reset_index(drop=True) for s, f in frames.items()}
        sg = {s: sig_full[s][mask(frames[s]).values].reset_index(drop=True) for s in frames}
        t = time.time()
        pos, acct, extra = engine.run(fr, sg, max_hold, fee)
        tr = report.trades_from_positions(pos)
        ev = report.evaluate(tr, 10_000.0)
        ev["blocked"] = extra["blocked"]; ev["halted"] = extra["halted"]
        res[label] = (ev, tr)
        log(f"[{name}] nautilus {label}: {ev['trades']} trades PF {ev['profit_factor']} DD {ev['max_drawdown_pct']}% in {time.time()-t:.0f}s")
    out = REPORTS / name
    out.mkdir(parents=True, exist_ok=True)
    meta = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": f"OKX 5m（1h 由 5m 重採樣）{len(frames)} 幣 {t0:%Y-%m-%d}→{t1:%Y-%m-%d}",
            "is_range": f"{t0:%Y-%m-%d %H:%M} → {split:%Y-%m-%d %H:%M} UTC", "oos_range": f"{split:%Y-%m-%d %H:%M} → {t1:%Y-%m-%d %H:%M} UTC",
            "params": params, "trials": opt.get("trials", 0), "optimizer": opt, "fee": fee, "nautilus": nautilus_trader.__version__,
            "oos_blocked": res["oos"][0]["blocked"]}
    write_json(out / "report.json", {"strategy": name, "meta": meta, "in_sample": res["is"][0], "out_of_sample": res["oos"][0]})
    (out / "report.md").write_text(report.to_markdown(name, meta, res["is"][0], res["oos"][0]), encoding="utf-8")
    res["oos"][1].to_csv(out / "oos_trades.csv", index=False)
    res["is"][1].to_csv(out / "is_trades.csv", index=False)
    passed = res["oos"][0]["passed"]
    registry.set_status(name, "PASSED" if passed else "REJECTED", params=params, timeframe=mod.TIMEFRAME,
                        evidence={"report_md": str(out / "report.md"), "report_json": str(out / "report.json"), "oos_trades": str(out / "oos_trades.csv")},
                        oos_summary={k: res["oos"][0][k] for k in ("trades", "profit_factor", "max_drawdown_pct", "net_pnl", "avg_net_per_trade")})
    return {"strategy": name, "passed": passed, "report": str(out / "report.md"), "oos": {k: v for k, v in res["oos"][0].items() if k not in ("by_pair", "by_month")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--no-opt", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run(a.strategy, a.trials, not a.no_opt), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
