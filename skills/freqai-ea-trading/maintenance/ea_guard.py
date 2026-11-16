#!/usr/bin/env python3
"""EA guard: keeps the BTC / ETH / SOL EAs honest after deployment.

Implements maintenance-protocol.md. Four commands:

  baseline  --coin btc --result <full-history.zip> [--before 2024-12-12]
            Expected behaviour of a deployed version from its validated history (block-bootstrap
            drawdowns, losing streaks, 10-trade profit factor, uptrend capture) -> baselines.json.
  forward   [--coin btc | --all] [--start 2026-11-01]
            Runs the frozen EA on data after the forward start (never seen during research) and
            grades it against its baseline. Writes a JSON + Markdown health report.
  replay    --coin btc --result <zip> --baseline-key btc@pre2024-12-12
            Month-by-month: what the guard would have said over a past period (agent self-test).
  live      [--act] [--loop 900]
            Polls the running bots' Freqtrade REST API: heartbeat, exchange stop orders,
            drawdown since high-water mark, losing streak, 10-trade profit factor.
            With --act it sends /stopentry to a bot whose state is HALT (never anything else).

Exit code: 0 HEALTHY/WATCH, 2 DEGRADED or ALERT, 3 HALT.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / "scripts"
BASELINES = HERE / "baselines.json"
LEVELS = ["HEALTHY", "WATCH", "DEGRADED", "HALT"]
ACTIONS = {
    "HEALTHY": "無需動作",
    "WATCH": "持續觀察，下次例行檢查再看",
    "DEGRADED": "開 issue；ea-maintainer 診斷原因；由人決定是否 /stopentry",
    "HALT": "停止新進場（/stopentry）；人工檢查後才可恢復",
}
PAIRS = {"btc": "BTC/USDT", "eth": "ETH/USDT", "sol": "SOL/USDT"}
FORWARD_START = "2026-11-01"
RNG = np.random.default_rng(20261116)


# ----------------------------------------------------------------- series helpers
def daily_series(zip_path: Path) -> tuple[pd.Series, pd.Series, list[dict], dict]:
    """Daily mark-to-market equity, daily buy & hold close, closed trades, raw strategy dict."""
    sys.path.insert(0, str(SCRIPTS))
    from mtm_report import equity_curve, load

    strat, _w, market = load(zip_path)
    eq, _pos = equity_curve(strat, market)
    m = market.copy()
    m["date"] = pd.to_datetime(m["date"], utc=True)
    px = m.set_index("date")["mean"].sort_index()
    eqd = eq.resample("1D").last().dropna()
    bhd = px.resample("1D").last().reindex(eqd.index).ffill()
    trades = sorted(strat["trades"], key=lambda t: t["close_timestamp"])
    return eqd, bhd, trades, strat


def trade_returns(trades: list[dict], start_balance: float) -> np.ndarray:
    eq, out = float(start_balance), []
    for t in trades:
        out.append(float(t["profit_abs"]) / eq)
        eq += float(t["profit_abs"])
    return np.array(out)


def max_drawdown(path: np.ndarray) -> float:
    peak = np.maximum.accumulate(path)
    return float(np.max(1 - path / peak)) if len(path) else 0.0


def profit_factor(r: np.ndarray) -> float:
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    return float("inf") if losses <= 0 else float(gains / losses)


def trailing_losses(r: np.ndarray) -> int:
    n = 0
    for x in r[::-1]:
        if x > 0:
            break
        n += 1
    return n


def max_streak(r: np.ndarray) -> int:
    best = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return best


# --------------------------------------------------------------------- baseline
def compute_baseline(eqd: pd.Series, bhd: pd.Series, r: np.ndarray, sims: int = 4000) -> dict:
    d = eqd.pct_change().fillna(0.0).to_numpy()
    block, horizon = 30, 365
    dds = np.empty(sims)
    for i in range(sims):
        starts = RNG.integers(0, max(1, len(d) - block), size=horizon // block + 1)
        path = np.concatenate([d[s : s + block] for s in starts])[:horizon]
        dds[i] = max_drawdown(np.cumprod(1 + path))
    streaks = np.array([max_streak(RNG.choice(r, 20)) for _ in range(sims)]) if len(r) else np.zeros(1)
    pf10 = np.array([profit_factor(RNG.choice(r, 10)) for _ in range(sims)]) if len(r) else np.zeros(1)
    pf10 = np.where(np.isfinite(pf10), pf10, 99.0)
    caps = []
    for end in pd.date_range(eqd.index[0] + pd.Timedelta(days=365), eqd.index[-1], freq="30D"):
        w_eq = eqd[(eqd.index > end - pd.Timedelta(days=365)) & (eqd.index <= end)]
        w_bh = bhd.reindex(w_eq.index)
        if len(w_eq) < 300:
            continue
        bh_ret = w_bh.iloc[-1] / w_bh.iloc[0] - 1
        if bh_ret >= 0.30:
            caps.append((w_eq.iloc[-1] / w_eq.iloc[0] - 1) / bh_ret)
    years = (eqd.index[-1] - eqd.index[0]).days / 365.25
    return {
        "dd_1y_p95": round(float(np.percentile(dds, 95)), 4),
        "dd_1y_p99": round(float(np.percentile(dds, 99)), 4),
        "dd_hist_max": round(max_drawdown(eqd.to_numpy()), 4),
        "streak_p95": int(np.percentile(streaks, 95)),
        "streak_p99": int(np.percentile(streaks, 99)),
        "streak_hist_max": max_streak(r),
        "pf10_p5": round(float(np.percentile(pf10, 5)), 3),
        "capture_p5": round(float(np.percentile(caps, 5)), 3) if len(caps) >= 3 else None,
        "capture_windows": len(caps),
        "trades": int(len(r)),
        "trades_per_year": round(len(r) / years, 2) if years > 0 else None,
        "history": f"{eqd.index[0].date()} -> {eqd.index[-1].date()}",
    }


def load_baselines() -> dict:
    return json.loads(BASELINES.read_text()) if BASELINES.exists() else {}


def cmd_baseline(a) -> None:
    eqd, bhd, trades, strat = daily_series(Path(a.result))
    if a.before:
        cut = pd.Timestamp(a.before, tz="UTC")
        eqd, bhd = eqd[eqd.index < cut], bhd[bhd.index < cut]
        trades = [t for t in trades if pd.Timestamp(t["close_timestamp"], unit="ms", tz="UTC") < cut]
    r = trade_returns(trades, strat["starting_balance"])
    b = compute_baseline(eqd, bhd, r)
    b.update({"strategy": strat["_name"], "source": Path(a.result).name,
              "computed_at": datetime.now(UTC).isoformat(timespec="seconds")})
    key = a.key or a.coin
    allb = load_baselines()
    allb[key] = b
    BASELINES.write_text(json.dumps(allb, indent=2, ensure_ascii=False) + "\n")
    print(key, json.dumps(b, ensure_ascii=False))


# --------------------------------------------------------------------- evaluate
def check(code: str, name: str, level: str, value, threshold, note: str = "") -> dict:
    return {"code": code, "name": name, "level": level, "value": value, "threshold": threshold, "note": note}


def evaluate(eqd: pd.Series, bhd: pd.Series, r: np.ndarray, base: dict, ic: dict | None = None) -> dict:
    checks = []
    path = eqd.to_numpy()
    cur_dd = float(1 - path[-1] / np.max(path)) if len(path) else 0.0
    worst_dd = max_drawdown(path)
    halt_dd = min(base["dd_1y_p99"], 1.5 * base["dd_hist_max"])
    # HALT acts on the drawdown now; WATCH also remembers the worst drawdown of the forward period
    lvl = "HALT" if cur_dd >= halt_dd else "WATCH" if max(cur_dd, worst_dd) >= base["dd_1y_p95"] else "HEALTHY"
    checks.append(check("C1", "回撤（目前 / 前向期最大）", lvl, [round(cur_dd, 4), round(worst_dd, 4)],
                        {"WATCH": base["dd_1y_p95"], "HALT": round(halt_dd, 4)}))
    streak = trailing_losses(r) if len(r) else 0
    lvl = "DEGRADED" if streak >= base["streak_p99"] else "WATCH" if streak >= base["streak_p95"] else "HEALTHY"
    checks.append(check("C2", "目前連敗", lvl, streak, {"WATCH": base["streak_p95"], "DEGRADED": base["streak_p99"]}))
    if len(r) >= 10:
        pf = profit_factor(r[-10:])
        lvl = "DEGRADED" if pf < base["pf10_p5"] else "HEALTHY"
        checks.append(check("C3", "最近 10 筆獲利因子", lvl, round(min(pf, 99.0), 3), {"DEGRADED": base["pf10_p5"]}))
    else:
        checks.append(check("C3", "最近 10 筆獲利因子", "HEALTHY", None, {"DEGRADED": base["pf10_p5"]},
                            f"前向只有 {len(r)} 筆，滿 10 筆才檢查"))
    span = (eqd.index[-1] - eqd.index[0]).days if len(eqd) else 0
    if span >= 365 and base.get("capture_p5") is not None:
        w = eqd[eqd.index > eqd.index[-1] - pd.Timedelta(days=365)]
        wb = bhd.reindex(w.index)
        bh_ret = float(wb.iloc[-1] / wb.iloc[0] - 1)
        ea_ret = float(w.iloc[-1] / w.iloc[0] - 1)
        if bh_ret >= 0.30:
            cap = ea_ret / bh_ret
            lvl = "DEGRADED" if cap < base["capture_p5"] else "HEALTHY"
            checks.append(check("C4", "上漲捕捉率（365 天）", lvl, round(cap, 3), {"DEGRADED": base["capture_p5"]},
                                f"持有 {bh_ret:+.1%}，EA {ea_ret:+.1%}"))
        else:
            checks.append(check("C4", "上漲捕捉率（365 天）", "HEALTHY", None, {"DEGRADED": base["capture_p5"]},
                                f"持有 {bh_ret:+.1%} < +30%，不適用"))
    else:
        checks.append(check("C4", "上漲捕捉率（365 天）", "HEALTHY", None, {"DEGRADED": base.get("capture_p5")},
                            f"前向 {span} 天，滿 365 天才檢查"))
    if ic is not None and ic.get("n", 0) >= 24 * 30:
        lvl = "WATCH" if ic["model"] < ic["naive"] else "HEALTHY"
        checks.append(check("C5", "FreqAI 波動預測 IC（90 天）", lvl, round(ic["model"], 3), {"WATCH": f"< 天真 {ic['naive']:.3f}"}))
    elif ic is not None:
        checks.append(check("C5", "FreqAI 波動預測 IC（90 天）", "HEALTHY", None, None,
                            f"只有 {ic.get('n', 0)} 小時可評分，滿 30 天才檢查"))
    status = max((c["level"] for c in checks), key=LEVELS.index)
    ret = float(path[-1] / path[0] - 1) if len(path) else 0.0
    bh = float(bhd.iloc[-1] / bhd.iloc[0] - 1) if len(bhd) else 0.0
    return {"status": status, "action": ACTIONS[status], "checks": checks,
            "period": f"{eqd.index[0].date()} -> {eqd.index[-1].date()}" if len(eqd) else "",
            "return_pct": round(100 * ret, 2), "buy_hold_pct": round(100 * bh, 2),
            "max_dd_pct": round(100 * max_drawdown(path), 2), "trades": int(len(r)),
            "profit_factor": round(min(profit_factor(r), 99.0), 2) if len(r) else None}


# ---------------------------------------------------------------------- forward
def candle_file(userdir: Path, pair: str, market: str = "spot") -> Path:
    base, quote = pair.split("/")
    if market == "perp":
        return userdir / "data" / "binance" / "futures" / f"{base}_{quote}_{quote}-1h-futures.feather"
    return userdir / "data" / "binance" / f"{base}_{quote}-1h.feather"


def freqai_ic(userdir: Path, identifier: str, pair: str, start: pd.Timestamp, days: int = 90,
              market: str = "spot") -> dict:
    files = sorted((userdir / "models" / identifier / "backtesting_predictions").glob("*_prediction.feather"))
    keep = [pd.read_feather(f) for f in files if (int(f.name.split("_")[2]) - int(start.timestamp())) % (30 * 86400) == 0
            and int(f.name.split("_")[2]) >= int(start.timestamp())]
    if not keep:
        return {"n": 0, "model": float("nan"), "naive": float("nan")}
    pr = pd.concat(keep).drop_duplicates("date").set_index("date").sort_index()
    c = pd.read_feather(candle_file(userdir, pair, market)).set_index("date")["close"]
    rv = np.log(c).diff().rolling(24).std()
    df = pd.DataFrame({"pred": rv * np.exp(pr["&-vol_ratio"].reindex(rv.index)), "naive": rv, "real": rv.shift(-24)}).dropna()
    df = df[df.index >= df.index.max() - pd.Timedelta(days=days)]
    if len(df) < 48:
        return {"n": int(len(df)), "model": float("nan"), "naive": float("nan")}
    return {"n": int(len(df)), "model": float(df["pred"].corr(df["real"], method="spearman")),
            "naive": float(df["naive"].corr(df["real"], method="spearman"))}


def latest_data_day(userdir: Path, pair: str, market: str = "spot") -> pd.Timestamp:
    d = pd.read_feather(candle_file(userdir, pair, market), columns=["date"])
    return d["date"].max().normalize() + pd.Timedelta(days=1)


def cmd_forward(a) -> int:
    sys.path.insert(0, str(SKILL / "scripts"))
    from ea_lab import run

    userdir = Path(a.userdir)
    coins = list(PAIRS) if a.all else [a.coin]
    allb = load_baselines()
    start = pd.Timestamp(a.start, tz="UTC")
    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "forward_start": a.start, "coins": {}}
    perp = a.market == "perp"
    for coin in coins:
        end = pd.Timestamp(a.end, tz="UTC") if a.end else latest_data_day(userdir, PAIRS[coin], a.market)
        tr = f"{start:%Y%m%d}-{end:%Y%m%d}"
        keep = Path(a.keep) / (f"{coin}_perp" if perp else coin) / f"{end:%Y%m%d}"
        r = run(coin, tr, None, None, 0.0005 if perp else 0.001, str(userdir), str(keep), n_jobs=a.n_jobs,
                market=a.market)
        if "error" in r:
            report["coins"][coin] = {"status": "ERROR", "error": r["error"][-1500:]}
            continue
        eqd, bhd, trades, strat = daily_series(Path(r["result_file"]))
        rr = trade_returns(trades, strat["starting_balance"])
        cfg = json.loads((SKILL / "user_data/configs" / f"config_{coin}_{'perp' if perp else 'ea'}.json").read_text())
        ic = freqai_ic(userdir, cfg["freqai"]["identifier"], PAIRS[coin], start, market=a.market)
        key = f"{coin}_perp" if perp else coin
        if key not in allb:
            report["coins"][key] = {"status": "ERROR", "error": f"baselines.json 沒有 {key}：先跑 baseline --key {key}"}
            continue
        ev = evaluate(eqd, bhd, rr, allb[key], ic)
        ev.update({"strategy": strat["_name"], "market": a.market, "timerange": tr, "result_file": r["result_file"],
                   "baseline": key, "freqai_ic": ic})
        if perp:
            ev.update({k: r.get(k) for k in ("long_trades", "long_pnl", "short_trades", "short_pnl", "funding_total",
                                             "liquidations")})
            if r.get("liquidations"):  # protocol section 8: the stop must always trigger before liquidation
                ev["checks"].append(check("C8", "強平", "ALERT", r["liquidations"], 0, "槓桿規則失效或資料異常"))
                if ev["status"] != "HALT":
                    ev["status"], ev["action"] = "ALERT", "出現強平：先停新進場，再診斷執行與資料"
        report["coins"][key] = ev
    return write_report(report, a.json, a.md)


def write_report(report: dict, json_path: str | None, md_path: str | None) -> int:
    worst = max((c.get("status", "HEALTHY") for c in report["coins"].values()),
                key=lambda s: LEVELS.index(s) if s in LEVELS else 2)
    report["overall"] = worst
    md = to_markdown(report)
    print(md)
    if json_path:
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    if md_path:
        Path(md_path).parent.mkdir(parents=True, exist_ok=True)
        Path(md_path).write_text(md)
    return {"HALT": 3, "DEGRADED": 2, "ERROR": 2, "ALERT": 2}.get(worst, 0)


def to_markdown(report: dict) -> str:
    lines = [f"## EA 健康檢查 {report['generated_at'][:10]}（前向起點 {report.get('forward_start', '-')}）", "",
             f"整體狀態：**{report.get('overall')}**", "",
             "| EA | 狀態 | 期間 | 報酬 | 持有 | 最大回撤 | 交易 | 建議動作 |", "|---|---|---|---|---|---|---|---|"]
    for coin, c in report["coins"].items():
        if c.get("status") == "ERROR":
            lines.append(f"| {coin.upper()} | ERROR | | | | | | {c['error'][-200:]} |")
            continue
        lines.append(f"| {coin.upper()} {c.get('strategy', '')} | **{c['status']}** | {c.get('period', '')} | "
                     f"{c.get('return_pct')}% | {c.get('buy_hold_pct')}% | {c.get('max_dd_pct')}% | {c.get('trades')} | {c['action']} |")
    for coin, c in report["coins"].items():
        if "checks" not in c:
            continue
        lines += ["", f"### {coin.upper()}", "", "| 檢查 | 狀態 | 數值 | 門檻 | 說明 |", "|---|---|---|---|---|"]
        for k in c["checks"]:
            lines.append(f"| {k['code']} {k['name']} | {k['level']} | {k['value']} | {k['threshold']} | {k['note']} |")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------- replay
def cmd_replay(a) -> None:
    eqd, bhd, trades, strat = daily_series(Path(a.result))
    base = load_baselines()[a.baseline_key]
    rows = []
    for t in pd.date_range(eqd.index[0] + pd.Timedelta(days=27), eqd.index[-1], freq="ME"):
        e, b = eqd[eqd.index <= t], bhd[bhd.index <= t]
        closed = [x for x in trades if pd.Timestamp(x["close_timestamp"], unit="ms", tz="UTC") <= t]
        ev = evaluate(e, b, trade_returns(closed, strat["starting_balance"]), base)
        why = [f"{k['code']}={k['value']}" for k in ev["checks"] if k["level"] != "HEALTHY"]
        rows.append({"month": f"{t:%Y-%m}", "status": ev["status"], "return_pct": ev["return_pct"],
                     "buy_hold_pct": ev["buy_hold_pct"], "max_dd_pct": ev["max_dd_pct"], "trades": ev["trades"], "why": why})
        print(f"{t:%Y-%m}  {ev['status']:9s} EA {ev['return_pct']:7.2f}%  持有 {ev['buy_hold_pct']:7.2f}%  "
              f"回撤 {ev['max_dd_pct']:5.2f}%  交易 {ev['trades']:2d}  {' '.join(why)}")
    if a.out:
        Path(a.out).write_text(json.dumps({"result": Path(a.result).name, "baseline": a.baseline_key, "months": rows},
                                          indent=2, ensure_ascii=False))


# ------------------------------------------------------------------------- live
def cmd_live(a) -> int:
    import requests

    bots = dict(x.split("=", 1) for x in os.environ.get("EA_GUARD_BOTS", "").split(",") if "=" in x)
    if not bots:
        sys.exit("set EA_GUARD_BOTS, e.g. btc=http://btc-ea:8080,eth=http://eth-ea:8080,sol=http://sol-ea:8080")
    auth = (os.environ.get("EA_GUARD_API_USER", ""), os.environ.get("EA_GUARD_API_PASSWORD", ""))
    state_path = Path(a.state)
    allb = load_baselines()
    while True:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "forward_start": "live", "coins": {}}
        for coin, url in bots.items():
            report["coins"][coin] = live_check(coin, url.rstrip("/"), auth, allb.get(coin) or allb[coin.split("_")[0]], state.setdefault(coin, {}), a.act, requests)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))
        code = write_report(report, a.json, a.md)
        notify(report)
        if not a.loop:
            return code
        time.sleep(a.loop)


def live_check(coin, url, auth, base, st, act, requests) -> dict:
    api = f"{url}/api/v1"
    try:
        requests.get(f"{api}/ping", timeout=10).raise_for_status()
        health = requests.get(f"{api}/health", auth=auth, timeout=10).json()
        bal = requests.get(f"{api}/balance", auth=auth, timeout=10).json()
        status = requests.get(f"{api}/status", auth=auth, timeout=10).json()
        closed = requests.get(f"{api}/trades", params={"limit": 50}, auth=auth, timeout=10).json().get("trades", [])
    except Exception as exc:  # noqa: BLE001 - any failure is an infrastructure alert
        return {"status": "ALERT", "action": "機器人無回應，檢查容器與網路", "checks": [], "error": str(exc)}
    now = datetime.now(UTC).timestamp()
    infra = []
    last = health.get("last_process_ts")
    if not last or now - last > 900:
        infra.append(f"超過 15 分鐘未處理（last_process_ts={last}）")
    for t in status:
        stops = [o for o in t.get("orders", []) if o.get("ft_order_side") == "stoploss" and o.get("is_open")]
        if not stops:
            infra.append(f"{t['pair']} 持倉沒有交易所停損單")
        upd = t.get("stoploss_last_update_timestamp")
        if upd and now - upd / 1000 > 3600:
            infra.append(f"{t['pair']} 停損超過 60 分鐘未更新")
    total = float(bal.get("total_bot") or bal.get("total") or 0.0)
    st["hwm"] = max(float(st.get("hwm", 0.0)), total)
    closed = sorted([t for t in closed if not t.get("is_open")], key=lambda t: t.get("close_timestamp") or 0)
    r = np.array([float(t["profit_abs"]) for t in closed])  # signs / ratios only: streak and profit factor
    eq = pd.Series([st["hwm"], total], index=pd.to_datetime([now - 1, now], unit="s", utc=True))
    ev = evaluate(eq, pd.Series([1.0, 1.0], index=eq.index), r, base)
    ev["checks"] = [c for c in ev["checks"] if c["code"] in ("C1", "C2", "C3")]
    ev["status"] = max((c["level"] for c in ev["checks"]), key=LEVELS.index)
    ev["action"] = ACTIONS[ev["status"]]
    ev.update({"equity": round(total, 2), "hwm": round(st["hwm"], 2), "open_trades": len(status)})
    if infra:
        ev["checks"].append(check("C6", "基礎設施", "ALERT", "；".join(infra), None))
        if ev["status"] != "HALT":
            ev["status"], ev["action"] = "ALERT", "修復基礎設施：" + "；".join(infra)
    if ev["status"] == "HALT" and act and not st.get("stopentry_sent"):
        resp = requests.post(f"{api}/stopentry", auth=auth, timeout=10)
        st["stopentry_sent"] = datetime.now(UTC).isoformat(timespec="seconds")
        ev["action"] = f"已送出 /stopentry（HTTP {resp.status_code}）；人工檢查後才可恢復"
    return ev


def notify(report: dict) -> None:
    token, chat = os.environ.get("EA_GUARD_TELEGRAM_TOKEN"), os.environ.get("EA_GUARD_TELEGRAM_CHAT_ID")
    bad = {k: v for k, v in report["coins"].items() if v.get("status") not in ("HEALTHY", "WATCH")}
    if not (token and chat and bad):
        return
    import requests

    text = "EA 守衛：" + "；".join(f"{k.upper()} {v['status']} → {v['action']}" for k, v in bad.items())
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("baseline")
    b.add_argument("--coin", required=True, choices=list(PAIRS))
    b.add_argument("--result", required=True)
    b.add_argument("--before", help="only use history before this date (YYYY-MM-DD)")
    b.add_argument("--key", help="baseline key (default: coin)")
    f = sub.add_parser("forward")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("--coin", choices=list(PAIRS))
    g.add_argument("--all", action="store_true")
    f.add_argument("--market", choices=["spot", "perp"], default="spot", help="perp = the USDT-M futures EAs")
    f.add_argument("--start", default=FORWARD_START)
    f.add_argument("--end", help="YYYY-MM-DD (default: day after the last candle on disk)")
    f.add_argument("--userdir", default=os.environ.get("FT_HOME", "user_data"))
    f.add_argument("--keep", default="ea_forward")
    f.add_argument("--n-jobs", type=int, default=2)
    f.add_argument("--json")
    f.add_argument("--md")
    r = sub.add_parser("replay")
    r.add_argument("--coin", required=True, choices=list(PAIRS))
    r.add_argument("--result", required=True)
    r.add_argument("--baseline-key", required=True)
    r.add_argument("--out")
    lv = sub.add_parser("live")
    lv.add_argument("--act", action="store_true", help="send /stopentry to bots in HALT")
    lv.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    lv.add_argument("--state", default=str(HERE / "state" / "live_state.json"))
    lv.add_argument("--json")
    lv.add_argument("--md")
    a = ap.parse_args()
    if a.cmd == "baseline":
        cmd_baseline(a)
    elif a.cmd == "forward":
        sys.exit(cmd_forward(a))
    elif a.cmd == "replay":
        cmd_replay(a)
    else:
        sys.exit(cmd_live(a))


if __name__ == "__main__":
    main()
