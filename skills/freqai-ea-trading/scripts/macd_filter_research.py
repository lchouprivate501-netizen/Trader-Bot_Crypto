#!/usr/bin/env python3
"""Self-Learning MACD Filter: research + validation reference implementation.

This file is the executable specification of tradingview/pine/self_learning_macd.pine.
Indicators reproduce Pine's ta.* exactly (EMA/RMA seeded with SMA, ATR = RMA of true range,
RSI = RMA-based), features and the online learner (RLS) are the same formulas in the same order.

  download   Binance public 15m klines (data.binance.vision) for the research symbols
  dev        build development events (dev symbols, before 2023-07-01) and fit the prior weights
  test       run the frozen indicator on the pre-registered test sets, write results JSON
  download-confirm / confirm   the confirmation test on 10 fresh symbols (4h, 1D), registered after `test`

  python3 scripts/macd_filter_research.py download --datadir /path/to/data
  python3 scripts/macd_filter_research.py dev  --datadir /path/to/data
  python3 scripts/macd_filter_research.py test --datadir /path/to/data --out references/results/macd_filter_test.json

Protocol: references/macd-filter-protocol.md   Results: references/macd-filter-research.md
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from numba import njit
except ImportError:  # pure-python fallback (slower, same results)
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

# ------------------------------------------------------------------ frozen configuration
DEV_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
HOLD_SYMS = ["ADAUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "TRXUSDT", "PAXGUSDT", "EURUSDT"]
TFS = ["15m", "1h", "4h", "1D"]
HTF_OF = {"15m": "1h", "1h": "4h", "4h": "1D", "1D": "1W"}
SPLIT = pd.Timestamp("2023-07-01")          # dev < SPLIT <= test
FAST, SLOW, SIG = 12, 26, 9
STOP_ATR = 1.5                                # 1R = 1.5 x ATR(14)
COST = 0.001                                  # round trip 0.10 %
MAX_BARS = 300
WARM = 250
CLIP = (-1.0, 5.0)                            # learning target clip (R)
LAMBDA = 100.0                                # prior strength (pseudo-samples)
FEATS = ["bias", "side", "htf_m", "htf_h", "ema_dist", "roc", "er", "volx", "vlm", "macdv", "rsi"]
W0 = np.array([0.0848, 0.0606, 0.3928, 0.0459, -0.3034, -0.0302, 0.1154, -0.2469, 0.2059, -0.0510, 0.1237])
TV_BARS = 5000                                # TradingView Basic-plan history (learner restarts)
# Confirmation test (registered after the v1.0 test, before these symbols were ever loaded)
CONFIRM_SYMS = ["DOTUSDT", "ATOMUSDT", "NEARUSDT", "UNIUSDT", "FILUSDT", "ETCUSDT", "BCHUSDT", "XLMUSDT", "AAVEUSDT", "ALGOUSDT"]
CONFIRM_TFS = ["4h", "1D"]


# ------------------------------------------------------------------ data
def download(datadir: Path, syms: list[str], start=(2019, 1), end=(2026, 10)) -> None:
    import requests
    datadir.mkdir(parents=True, exist_ok=True)

    def months():
        y, m = start
        while (y, m) <= end:
            yield f"{y:04d}-{m:02d}"
            m += 1
            if m == 13:
                y, m = y + 1, 1

    def fetch(sym, ym):
        url = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/15m/{sym}-15m-{ym}.zip"
        for _ in range(4):
            try:
                r = requests.get(url, timeout=60)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    df = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(6))
                if not str(df.iloc[0, 0]).isdigit():
                    df = df.iloc[1:]
                df.columns = ["ts", "open", "high", "low", "close", "volume"]
                df = df.astype(float)
                ts = df.ts.values.copy()
                ts[ts > 1e14] /= 1000          # 2025+ archives are in microseconds
                df["ts"] = ts.astype("int64")
                return df
            except Exception:
                continue
        raise RuntimeError(f"download failed: {url}")

    for sym in syms:
        with ThreadPoolExecutor(16) as ex:
            parts = [p for p in ex.map(lambda ym: fetch(sym, ym), list(months())) if p is not None]
        df = pd.concat(parts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        df.to_parquet(datadir / f"{sym}-15m.parquet")
        print(sym, len(df), flush=True)


_CACHE: dict = {}


def load(datadir: Path, sym: str, tf: str) -> pd.DataFrame:
    key = (str(datadir), sym, tf)
    if key in _CACHE:
        return _CACHE[key]
    df = pd.read_parquet(datadir / f"{sym}-15m.parquet")
    df["t"] = pd.to_datetime(df.ts, unit="ms")
    df = df.set_index("t")[["open", "high", "low", "close", "volume"]]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if tf == "15m":
        out = df
    elif tf == "1W":  # TradingView crypto weeks start Monday 00:00 UTC
        out = df.resample("W-MON", label="left", closed="left").agg(agg)
    else:
        out = df.resample({"1h": "1h", "4h": "4h", "1D": "1D"}[tf], label="left", closed="left").agg(agg)
    out = out.dropna()
    _CACHE[key] = out
    return out


# ------------------------------------------------------------------ Pine-identical TA
@njit(cache=True)
def _smooth(x, n, a):
    out = np.full(x.shape[0], np.nan)
    s = 0.0
    cnt = 0
    prev = np.nan
    for i in range(x.shape[0]):
        v = x[i]
        if np.isnan(prev):
            if np.isnan(v):
                cnt = 0
                s = 0.0
                continue
            s += v
            cnt += 1
            if cnt >= n:
                prev = s / n
                out[i] = prev
        else:
            if not np.isnan(v):
                prev = a * v + (1 - a) * prev
            out[i] = prev
    return out


def ema(x, n):
    return _smooth(np.asarray(x, float), n, 2.0 / (n + 1))


def rma(x, n):
    return _smooth(np.asarray(x, float), n, 1.0 / n)


@njit(cache=True)
def true_range(h, l, c):
    tr = np.empty(h.shape[0])
    tr[0] = h[0] - l[0]
    for i in range(1, h.shape[0]):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return tr


def atr(h, l, c, n):
    return rma(true_range(h, l, c), n)


@njit(cache=True)
def rolling_sum(x, n):
    out = np.full(x.shape[0], np.nan)
    s = 0.0
    for i in range(x.shape[0]):
        s += x[i]
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s
    return out


@njit(cache=True)
def er_dir(c, n):
    out = np.full(c.shape[0], np.nan)
    for i in range(n, c.shape[0]):
        den = 0.0
        for j in range(i - n + 1, i + 1):
            den += abs(c[j] - c[j - 1])
        out[i] = (c[i] - c[i - n]) / den if den > 0 else 0.0
    return out


def rsi(c, n):
    ch = np.r_[np.nan, np.diff(c)]
    ru = rma(np.where(np.isnan(ch), np.nan, np.maximum(ch, 0)), n)
    rd = rma(np.where(np.isnan(ch), np.nan, np.maximum(-ch, 0)), n)
    with np.errstate(all="ignore"):
        out = np.where(rd == 0, 100.0, np.where(ru == 0, 0.0, 100 - 100 / (1 + ru / rd)))
    return np.where(np.isnan(ru) | np.isnan(rd), np.nan, out)


def macd_core(df):
    h, l, c = (df[k].values.astype(float) for k in ["high", "low", "close"])
    m = ema(c, FAST) - ema(c, SLOW)
    s = ema(m, SIG)
    return m, s, m - s, atr(h, l, c, SLOW)


def htf_values(datadir, sym, tf, chart_index):
    """request.security(htf, [mv[1], hv[1]], lookahead_on): last *completed* HTF bar."""
    hd = load(datadir, sym, HTF_OF[tf])
    m, s, hist, a = macd_core(hd)
    mv = np.r_[np.nan, (m / a)[:-1]]
    hv = np.r_[np.nan, (hist / a)[:-1]]
    pos = np.clip(hd.index.searchsorted(chart_index, side="right") - 1, 0, len(hd) - 1)
    return mv[pos], hv[pos]


# ------------------------------------------------------------------ trade outcome (label of every cross)
@njit(cache=True)
def classic_exit(o, h, l, c, idx, side, atrv, hist, sl_k, maxbars):
    """Entry at the cross close. Exit: protective stop first (gap fills at the open), else the
    close of the next opposite cross, else the close MAX_BARS later. Gross R (1R = sl_k*ATR)."""
    m = idx.shape[0]
    n = c.shape[0]
    R = np.full(m, np.nan)
    xb = np.full(m, -1)
    for k in range(m):
        i = idx[k]
        d = side[k]
        e = c[i]
        risk = sl_k * atrv[i]
        if not (risk > 0):
            continue
        sl = e - d * risk
        res = np.nan
        j = i
        for j in range(i + 1, min(i + 1 + maxbars, n)):
            if (d > 0 and l[j] <= sl) or (d < 0 and h[j] >= sl):
                fill = min(sl, o[j]) if d > 0 else max(sl, o[j])
                res = d * (fill - e) / risk
                break
            if (d > 0 and hist[j] < 0) or (d < 0 and hist[j] > 0):
                res = d * (c[j] - e) / risk
                break
        if np.isnan(res):
            if i + maxbars >= n:
                continue                   # unresolved at the end of the data: never learned from
            j = i + maxbars
            res = d * (c[j] - e) / risk
        R[k] = res
        xb[k] = j
    return R, xb


def tanh(x):
    return np.tanh(np.clip(x, -20, 20))


def build_events(datadir, sym, tf):
    """Every MACD/signal cross with the 11 Pine features, cost in R and the trade outcome."""
    df = load(datadir, sym, tf)
    o, h, l, c, v = (df[k].values.astype(float) for k in ["open", "high", "low", "close", "volume"])
    m, s, hist, a_slow = macd_core(df)
    a14 = atr(h, l, c, 14)
    a100 = atr(h, l, c, 100)
    e200 = ema(c, 200)
    r14 = rsi(c, 14)
    erd = er_dir(c, 20)
    vn = np.nan_to_num(v)
    vs = rolling_sum(vn, 50) / 50
    hm, hh = htf_values(datadir, sym, tf, df.index)
    prev = np.r_[np.nan, hist[:-1]]
    up = (hist > 0) & (prev <= 0)
    dn = (hist < 0) & (prev >= 0)
    up[:WARM] = False
    dn[:WARM] = False
    idx = np.where(up | dn)[0]
    d = np.where(up[idx], 1.0, -1.0)
    c100 = np.r_[np.full(100, np.nan), c[:-100]]
    with np.errstate(all="ignore"):
        vr = np.where(vs[idx] > 0, vn[idx] / vs[idx], 1.0)
        F = {
            "bias": np.ones(len(idx)),
            "side": d,
            "htf_m": tanh(d * hm[idx]),
            "htf_h": tanh(d * 10 * hh[idx]),
            "ema_dist": tanh(d * (c[idx] - e200[idx]) / a14[idx] / 5),
            "roc": tanh(d * (c[idx] / c100[idx] - 1) / (a14[idx] / c[idx]) / 10),
            "er": d * erd[idx],
            "volx": tanh(2 * np.log(a14[idx] / a100[idx])),
            "vlm": np.where(vr > 0, tanh(np.log(np.where(vr > 0, vr, 1.0))), -1.0),
            "macdv": tanh(d * m[idx] / a_slow[idx]),
            "rsi": d * (r14[idx] - 50) / 50,
        }
        cost_r = COST * c[idx] / (STOP_ATR * a14[idx])
    R, xb = classic_exit(o, h, l, c, idx, d.astype(np.int64), a14, hist, STOP_ATR, MAX_BARS)
    ev = pd.DataFrame(F)
    ev["cost_r"] = cost_r
    ev["t"] = df.index[idx]
    ev["i"] = idx
    ev["Rg"] = R
    ev["R"] = R - cost_r
    ev["sym"] = sym
    ev["tf"] = tf
    ok = ev[FEATS + ["cost_r"]].notna().all(axis=1) & (a14[idx] > 0)
    return ev[ok].reset_index(drop=True), df


# ------------------------------------------------------------------ the learner (same as the Pine RLS)
def run_learner(ev: pd.DataFrame, w0=W0, lam=LAMBDA, learn=True, reset_every=None):
    """Sequential: predict each cross with the current weights, then learn from its outcome.
    The outcome of cross k is known at or before cross k+1 (exit <= next cross), as in Pine."""
    k = len(FEATS)
    X = ev[FEATS].values
    Y = np.clip(ev.Rg.values, *CLIP)
    I = ev.i.values
    w = w0.copy()
    P = np.eye(k) / lam
    cur = None
    pred = np.empty(len(ev))
    for j in range(len(ev)):
        if reset_every is not None and I[j] // reset_every != cur:
            cur = I[j] // reset_every
            w = w0.copy()
            P = np.eye(k) / lam
        x = X[j]
        pred[j] = w @ x
        if learn and not np.isnan(Y[j]):
            px = P @ x
            den = 1.0 + x @ px
            w = w + px / den * (Y[j] - w @ x)
            P = P - np.outer(px, px) / den
    return pred


def fit_prior(E: pd.DataFrame, lam_frac=1e-3):
    """Ridge on clipped gross R, each timeframe weighted equally."""
    wt = E.groupby("tf").R.transform(lambda s: 1 / len(s)).values
    wt = wt / wt.sum() * len(E)
    X = E[FEATS].values
    y = np.clip(E.Rg.values, *CLIP)
    Ws = np.sqrt(wt)[:, None]
    A = (X * Ws).T @ (X * Ws) + lam_frac * len(E) * np.eye(len(FEATS))
    return np.linalg.solve(A, (X * Ws).T @ (y * np.sqrt(wt)))


# ------------------------------------------------------------------ evaluation
def combo_stats(g: pd.DataFrame, keep: np.ndarray) -> dict:
    r_all = g.R.values
    r = r_all[keep]
    gp, gl = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "n_raw": int(len(r_all)), "n_filt": int(len(r)),
        "raw_mean_R": float(r_all.mean()) if len(r_all) else None,
        "filt_mean_R": float(r.mean()) if len(r) else None,
        "raw_false_rate": float((r_all <= 0).mean()) if len(r_all) else None,
        "filt_false_rate": float((r <= 0).mean()) if len(r) else None,
        "raw_pf": float(r_all[r_all > 0].sum() / -r_all[r_all < 0].sum()) if (r_all < 0).any() else None,
        "filt_pf": float(gp / gl) if gl > 0 else None,
        "raw_sum_R": float(r_all.sum()), "filt_sum_R": float(r.sum()),
    }


def equity(rs: np.ndarray, risk=0.01):
    eq = np.cumprod(1 + risk * rs) if len(rs) else np.array([1.0])
    peak = np.maximum.accumulate(np.r_[1.0, eq])
    dd = (np.r_[1.0, eq] / peak - 1).min()
    return float(eq[-1] - 1), float(-dd)


def buy_hold(df: pd.DataFrame, start, end=None):
    c = df.close[(df.index >= start) & ((df.index < end) if end is not None else True)]
    if len(c) < 2:
        return None, None
    ret = c.iloc[-1] / c.iloc[0] - 1
    dd = (c / c.cummax() - 1).min()
    return float(ret), float(-dd)


def bootstrap_ci(diffs: np.ndarray, n=10000, seed=7):
    rng = np.random.default_rng(seed)
    bs = rng.choice(diffs, size=(n, len(diffs)), replace=True).mean(axis=1)
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def cmd_dev(args):
    E = pd.concat([build_events(args.datadir, s, tf)[0] for tf in TFS for s in DEV_SYMS])
    E = E[(E.t < SPLIT) & E.R.notna()]
    w = fit_prior(E)
    print("dev events:", len(E), E.groupby("tf").size().to_dict())
    print("prior:", dict(zip(FEATS, np.round(w, 4))))
    print("frozen W0 matches:", bool(np.allclose(np.round(w, 4), W0)))


def cmd_test(args, syms=None, confirm=False):
    out = {"config": {"features": FEATS, "w0": W0.tolist(), "lambda": LAMBDA, "stop_atr": STOP_ATR, "cost": COST,
                      "split": str(SPLIT.date()), "macd": [FAST, SLOW, SIG], "threshold": "pred - cost_R > 0"},
           "combos": []}
    for sym in (syms or DEV_SYMS + HOLD_SYMS):
        for tf in TFS:
            ev, df = build_events(args.datadir, sym, tf)
            preds = {
                "online": run_learner(ev),
                "static": run_learner(ev, learn=False),
                "online_tv5000": run_learner(ev, reset_every=TV_BARS),
            }
            group = "dev" if sym in DEV_SYMS else ("confirm" if confirm else "holdout")
            for period, mask in [("test", (ev.t >= SPLIT).values), ("dev", (ev.t < SPLIT).values)]:
                if period == "dev" and group in ("dev", "confirm"):
                    continue                       # in-sample for the prior: not reported
                g = ev[mask & ev.R.notna().values]
                row = {"sym": sym, "tf": tf, "group": group, "period": period}
                for name, p in preds.items():
                    keep = (p[mask & ev.R.notna().values] - g.cost_r.values) > 0
                    st = combo_stats(g, keep)
                    if name == "online":
                        row.update(st)
                        row["eq_raw_ret"], row["eq_raw_dd"] = equity(g.R.values)
                        row["eq_filt_ret"], row["eq_filt_dd"] = equity(g.R.values[keep])
                        lk = keep & (g.side.values > 0)
                        row["filt_long_n"], row["filt_long_mean_R"] = int(lk.sum()), float(g.R.values[lk].mean()) if lk.any() else None
                        sk = keep & (g.side.values < 0)
                        row["filt_short_n"], row["filt_short_mean_R"] = int(sk.sum()), float(g.R.values[sk].mean()) if sk.any() else None
                    else:
                        row[f"{name}_n_filt"] = st["n_filt"]
                        row[f"{name}_filt_mean_R"] = st["filt_mean_R"]
                        row[f"{name}_filt_false_rate"] = st["filt_false_rate"]
                start = SPLIT if period == "test" else df.index[WARM]
                end = None if period == "test" else SPLIT
                row["bh_ret"], row["bh_dd"] = buy_hold(df, start, end)
                out["combos"].append(row)
                print(f"{sym:9s} {tf:4s} {period:4s} raw {row['raw_mean_R']:+.3f} (n={row['n_raw']})  "
                      f"filt {row['filt_mean_R'] if row['filt_mean_R'] is not None else float('nan'):+.3f} (n={row['n_filt']})  "
                      f"static {row['static_filt_mean_R'] if row['static_filt_mean_R'] is not None else float('nan'):+.3f}  "
                      f"tv5000 {row['online_tv5000_filt_mean_R'] if row['online_tv5000_filt_mean_R'] is not None else float('nan'):+.3f}",
                      flush=True)
    C = pd.DataFrame(out["combos"])
    out["verdict"] = verdict_confirm(C) if confirm else verdict(C)
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(out["verdict"], indent=1, ensure_ascii=False))


def verdict(C: pd.DataFrame) -> dict:
    """Pre-registered criteria (references/macd-filter-protocol.md)."""
    def p1(sub, col="filt_mean_R", ncol="n_filt"):
        s = sub[sub[ncol] >= 10]
        diffs = (s[col] - s.raw_mean_R).values
        return s, diffs
    T = C[C.period == "test"]
    s, diffs = p1(T)
    lo, hi = bootstrap_ci(diffs)
    res = {}
    res["P1_test_mean_diff_R"] = float(diffs.mean())
    res["P1_test_ci95"] = [lo, hi]
    res["P1_pass"] = bool(lo > 0)
    res["P1_combos_used"] = int(len(s))
    res["P1_combos_excluded_lt10"] = int(len(T) - len(s))
    res["P2_share_improved"] = float((diffs > 0).mean())
    res["P2_pass"] = bool((diffs > 0).mean() >= 0.70)
    fr = (s.filt_false_rate - s.raw_false_rate).values
    res["P3_false_rate_raw"] = float(s.raw_false_rate.mean())
    res["P3_false_rate_filt"] = float(s.filt_false_rate.mean())
    res["P3_pass"] = bool(fr.mean() < 0)
    sh, dh = p1(T[T.group == "holdout"])
    res["P4_holdout_test_mean_diff_R"] = float(dh.mean())
    res["P4_pass"] = bool(dh.mean() > 0)
    both = T[(T.n_filt >= 10) & (T.static_n_filt >= 10)]
    res["P5_online_mean_R"] = float(both.filt_mean_R.mean())
    res["P5_static_mean_R"] = float(both.static_filt_mean_R.mean())
    res["P5_pass"] = bool(both.filt_mean_R.mean() >= both.static_filt_mean_R.mean())
    s6, d6 = p1(T, "online_tv5000_filt_mean_R", "online_tv5000_n_filt")
    res["P6_tv5000_mean_diff_R"] = float(d6.mean())
    res["P6_pass"] = bool(d6.mean() > 0)
    S = C[C.period == "dev"]
    s7, d7 = p1(S)
    res["secondary_holdout_dev_period_mean_diff_R"] = float(d7.mean())
    res["by_tf_test"] = {tf: {"raw_mean_R": float(g.raw_mean_R.mean()),
                              "filt_mean_R": float(g[g.n_filt >= 10].filt_mean_R.mean()) if (g.n_filt >= 10).any() else None,
                              "kept_share": float(g.n_filt.sum() / g.n_raw.sum()),
                              "raw_false_rate": float(g.raw_false_rate.mean()),
                              "filt_false_rate": float(g[g.n_filt >= 10].filt_false_rate.mean()) if (g.n_filt >= 10).any() else None}
                         for tf, g in T.groupby("tf")}
    res["all_primary_pass"] = bool(res["P1_pass"] and res["P2_pass"] and res["P3_pass"] and res["P4_pass"])
    return res


def verdict_confirm(C: pd.DataFrame) -> dict:
    """Confirmation criteria C1-C4 (references/macd-filter-protocol.md, 確認測試)."""
    T = C[(C.period == "test") & C.tf.isin(CONFIRM_TFS)]
    s = T[T.n_filt >= 10]
    diffs = (s.filt_mean_R - s.raw_mean_R).values
    lo, hi = bootstrap_ci(diffs)
    res = {"scope": CONFIRM_TFS, "combos_used": int(len(s)), "combos_excluded_lt10": int(len(T) - len(s)),
           "C1_mean_diff_R": float(diffs.mean()), "C1_ci95": [lo, hi], "C1_pass": bool(lo > 0),
           "C2_share_improved": float((diffs > 0).mean()), "C2_pass": bool((diffs > 0).mean() >= 0.70),
           "C3_false_rate_raw": float(s.raw_false_rate.mean()), "C3_false_rate_filt": float(s.filt_false_rate.mean()),
           "C3_pass": bool(s.filt_false_rate.mean() < s.raw_false_rate.mean()),
           "C4_filt_mean_R": float(s.filt_mean_R.mean()), "C4_pass": bool(s.filt_mean_R.mean() > 0)}
    res["all_pass"] = bool(res["C1_pass"] and res["C2_pass"] and res["C3_pass"] and res["C4_pass"])
    D = C[C.period == "test"]
    res["descriptive_by_tf"] = {tf: {"raw_mean_R": float(g.raw_mean_R.mean()),
                                     "filt_mean_R_n10": float(g[g.n_filt >= 10].filt_mean_R.mean()) if (g.n_filt >= 10).any() else None,
                                     "improved_share_n10": float(((g.filt_mean_R - g.raw_mean_R)[g.n_filt >= 10] > 0).mean()) if (g.n_filt >= 10).any() else None,
                                     "kept_share": float(g.n_filt.sum() / g.n_raw.sum())} for tf, g in D.groupby("tf")}
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["download", "dev", "test", "download-confirm", "confirm"])
    ap.add_argument("--datadir", type=Path, required=True)
    ap.add_argument("--out", default="references/results/macd_filter_test.json")
    args = ap.parse_args()
    if args.cmd == "download":
        download(args.datadir, DEV_SYMS + HOLD_SYMS)
    elif args.cmd == "download-confirm":
        download(args.datadir, CONFIRM_SYMS)
    elif args.cmd == "dev":
        cmd_dev(args)
    elif args.cmd == "confirm":
        cmd_test(args, syms=CONFIRM_SYMS, confirm=True)
    else:
        cmd_test(args)


if __name__ == "__main__":
    sys.exit(main())
