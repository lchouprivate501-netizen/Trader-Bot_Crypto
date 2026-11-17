#!/usr/bin/env python3
"""日內篩選器的驗證研究（Binance USDT 永續全部合約、data.binance.vision 歷史資料、只用標準函式庫）。

問題：用「到今天為止」的指標挑幣，明天這些幣是否真的比較少盤整、比較有波動？
   - 每天收盤（UTC 00:00）用前 14 天資料算指標 → 套用篩選器的硬門檻 → 量測「隔天」的結果
   - 結果：隔天 4 小時區塊效率比（ER）、盤整率（ER < chop_er 的區塊比例）、4 小時淨移動 %、日振幅 %
   - 比較：篩選器前 K 名 vs 全部合格幣平均 vs 常見做法（成交額前 K、24h 漲跌幅前 K、振幅前 K）
   - 研發期 / 保留期分開：權重只看研發期決定，保留期只跑一次

用法：
  python3 research.py download --start 2025-11 --end 2026-10 --daily-tail     # 約 8,000 個檔、幾分鐘
  python3 research.py factors  --until 2026-05-31                              # 研發期：各指標的預測力
  python3 research.py evaluate --from 2026-06-01                               # 保留期：前 K 名 vs 對照組
  python3 research.py intraday --from 2026-06-01                               # 盤中狀態、時段、星期
  python3 research.py gates    --until 2026-05-31                              # 成交額、振幅門檻的效果
  python3 research.py forward  --log ~/.intraday-screener/runs                 # 前向驗證：scan --log 的紀錄 vs 之後 24 小時
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intraday_screener as sc  # noqa: E402

CACHE = Path(os.environ.get("SCREENER_CACHE", Path.home() / ".cache" / "intraday-screener"))
OUTCOMES = ("er4h", "chop", "move4h", "rng")


def ymd(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def to_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def months(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ye, me = map(int, end.split("-"))
    out = []
    while (y, m) <= (ye, me):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ----------------------------------------------------------------------------------------------
# 下載 → 每天的統計（chunk_stats）存成 JSON；K 線本身不保留
# ----------------------------------------------------------------------------------------------

def bars_to_days(bars: list) -> dict:
    by = defaultdict(list)
    for b in bars:
        by[b[0] // sc.DAY_MS * sc.DAY_MS].append(b)
    out = {}
    for start, bs in by.items():
        st = sc.chunk_stats(sorted(bs), start)
        if st:
            st.pop("o", None), st.pop("h", None), st.pop("l", None)
            st["s1"], st["s4"], st["s16"] = (round(st[k], 8) for k in ("s1", "s4", "s16"))
            out[ymd(start)] = st
    return out


def download_symbol(sym: str, mos: list[str], tail_days: list[str]) -> tuple[str, int]:
    path = CACHE / "daystats" / f"{sym.encode('ascii', 'backslashreplace').decode().replace(chr(92), '_')}.json"
    have = json.loads(path.read_text()) if path.exists() else {}
    done_mo = {d[:7] for d in have}
    bars = []
    for mo in mos:
        if mo in done_mo:
            continue
        bars += sc.archive_klines(sym, mo) or []
    active = any(d[:7] == mos[-1] for d in have) or (bars and bars[-1][0] >= to_ms(mos[-1] + "-01"))
    for d in tail_days if active else []:  # 最後一個月沒交易（已下架）就不用找日檔
        if d not in have:
            bars += sc.archive_klines(sym, d) or []
    have.update(bars_to_days(bars))
    if have:
        path.write_text(json.dumps(have, separators=(",", ":")))
    return sym, len(have)


def cmd_download(a) -> None:
    (CACHE / "daystats").mkdir(parents=True, exist_ok=True)
    syms = sorted(set(sc.archive_symbols("monthly")) | set(sc.archive_symbols("daily")))
    print(f"{len(syms)} 個 USDT 永續代號（含已下架）", flush=True)
    mos = months(a.start, a.end)
    tail = []
    if a.daily_tail:
        y, m = map(int, a.end.split("-"))
        first = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        last = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        d = first
        while d <= last:
            tail.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
    n = 0
    with ThreadPoolExecutor(a.workers) as pool:
        for sym, days in pool.map(lambda s: download_symbol(s, mos, tail), syms):
            n += 1
            if n % 50 == 0 or n == len(syms):
                print(f"  {n}/{len(syms)}  {sym}: {days} 天", flush=True)


# ----------------------------------------------------------------------------------------------
# 面板：每天每個幣的指標（決策時點 = 當天 UTC 收盤）與隔天結果
# ----------------------------------------------------------------------------------------------

def load_panel() -> dict:
    out = {}
    for p in sorted((CACHE / "daystats").glob("*.json")):
        days = json.loads(p.read_text())
        for d in days.values():
            if "chg" not in d:  # 舊快取：由 24 個 1 小時對數報酬還原漲跌
                d["chg"] = round((math.exp(sum(x for x in d["hr"] if x)) - 1) * 100, 4)
        for k, d in days.items():
            d["t"] = to_ms(k)
        out[p.stem] = days
    return out


def outcome(day: dict, cfg: dict) -> dict | None:
    if not day or len(day["blocks"]) < 6:
        return None
    bl = day["blocks"]
    return {
        "er4h": sum(b[0] for b in bl) / len(bl),
        "chop": sum(1 for b in bl if b[0] < cfg["chop_er"]) / len(bl),
        "move4h": sum(b[1] for b in bl) / len(bl),
        "rng": day["rng"],
    }


def build(panel: dict, cfg: dict, d_from: str, d_to: str) -> list[dict]:
    """回傳每個決策日的截面：[{date, rows:[{sym, metrics, factors, reject, y}]}]。"""
    L = cfg["lookback_days"]
    first_seen = {s: min(days) for s, days in panel.items() if days}
    start, end = to_ms(d_from), to_ms(d_to)
    out = []
    t = start
    while t <= end:
        dates = [ymd(t - (L - 1 - i) * sc.DAY_MS) for i in range(L)]
        nxt = ymd(t + sc.DAY_MS)
        rows = []
        for s, days in panel.items():
            if dates[-1] not in days:
                continue
            y = outcome(days.get(nxt), cfg)
            if y is None:
                continue
            win = [days.get(d) for d in dates]
            m = sc.window_metrics(win, cfg)
            if m is None:
                continue
            age = (t - to_ms(first_seen[s])) / sc.DAY_MS + 1
            row = {"sym": s, "base": s[:-4], "coin": s[:-4], "metrics": m, "age_days": age, "y": y}
            row["reject"] = sc.gate(row, cfg)
            rows.append(row)
        if rows:
            out.append({"date": dates[-1], "rows": rows})
        t += sc.DAY_MS
    return out


def spearman(a: list, b: list) -> float | None:
    if len(a) < 10:
        return None
    ra, rb = sc.pct_ranks(a), sc.pct_ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    sab = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    saa = sum((x - ma) ** 2 for x in ra)
    sbb = sum((y - mb) ** 2 for y in rb)
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None


def tstat(xs: list) -> tuple[float, float]:
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return float("nan"), float("nan")
    m = statistics.mean(xs)
    sd = statistics.stdev(xs)
    # 截面 IC 每天重疊的 14 天回看讓相鄰日相關：用 Newey-West 式的保守做法，有效樣本數除以 5
    n_eff = max(len(xs) / 5, 2)
    return m, (m / (sd / math.sqrt(n_eff)) if sd > 0 else float("nan"))


FACTORS = sc.FACTORS


def cmd_factors(a, cfg) -> dict:
    panel = load_panel()
    secs = build(panel, cfg, a.date_from, a.until)
    res = {"period": [secs[0]["date"], secs[-1]["date"]], "days": len(secs), "ic": {}}
    print(f"截面 {len(secs)} 天（{res['period'][0]} → {res['period'][1]}），"
          f"每天合格幣數 中位數 {statistics.median(sum(not r['reject'] for r in s['rows']) for s in secs):.0f}")
    print(f"\n{'指標':<26}" + "".join(f"{'IC→' + y:>14}" for y in OUTCOMES))
    for name, (fn, zh) in FACTORS.items():
        line = f"{name:<12}{zh:<14}"
        res["ic"][name] = {}
        for y in OUTCOMES:
            ics = []
            for s in secs:
                ok = [r for r in s["rows"] if not r["reject"]]
                xs = [fn(r["metrics"]) for r in ok]
                ys = [r["y"][y] for r in ok]
                pairs = [(x, v) for x, v in zip(xs, ys) if x is not None]
                if len(pairs) >= 10:
                    ics.append(spearman(*map(list, zip(*pairs))))
            m, t = tstat(ics)
            res["ic"][name][y] = {"ic": round(m, 4), "t": round(t, 2)}
            line += f"{m:>+8.3f} (t{t:>+4.1f})"
        print(line)
    print("\n盤整率（chop）是越低越好，所以對 chop 的 IC 為負代表「指標高 → 隔天比較少盤整」。")
    # 因子之間的截面相關（協議：> 0.9 的只留一個）
    names = list(FACTORS)
    cc = defaultdict(list)
    for s in secs[::3]:
        ok = [r for r in s["rows"] if not r["reject"]]
        vals = {n: [FACTORS[n][0](r["metrics"]) for r in ok] for n in names}
        for i, a_ in enumerate(names):
            for b_ in names[i + 1:]:
                pairs = [(x, y) for x, y in zip(vals[a_], vals[b_]) if x is not None and y is not None]
                if len(pairs) >= 10:
                    cc[(a_, b_)].append(spearman(*map(list, zip(*pairs))))
    res["factor_corr"] = {f"{a_}~{b_}": round(statistics.mean(v), 3) for (a_, b_), v in cc.items()}
    hi = sorted(((abs(v), k, v) for k, v in res["factor_corr"].items() if abs(v) >= 0.7), reverse=True)
    print("\n因子之間的截面相關 |ρ| ≥ 0.7：")
    for _, k, v in hi:
        print(f"  {k:<26}{v:+.3f}")
    return res


def rankers(cfg: dict) -> dict:
    def comp(rows):
        sc.score_rows(rows, cfg)
        return {id(r): r.get("score", 0) for r in rows}
    return {
        "篩選器分數": ("score", comp),
        "成交額前 K（只看流動性）": ("qv", lambda rows: {id(r): r["metrics"]["qv_24h"] for r in rows}),
        "24h 漲跌幅前 K（漲跌排行榜）": ("chg", lambda rows: {id(r): abs(r["metrics"]["chg_24h_pct"]) for r in rows}),
        "振幅前 K（只看波動）": ("rng", lambda rows: {id(r): r["metrics"]["range_pct"] for r in rows}),
        "RVOL 前 K（只看熱度）": ("rvol", lambda rows: {id(r): r["metrics"]["rvol"] or 0 for r in rows}),
    }


def cmd_evaluate(a, cfg, quiet=False) -> dict:
    panel = load_panel()
    secs = build(panel, cfg, a.date_from, a.until)
    K = a.k
    out = {"period": [secs[0]["date"], secs[-1]["date"]], "days": len(secs), "k": K, "groups": {}}
    groups = {"全部合格幣（平均）": None, **rankers(cfg)}
    acc = {g: defaultdict(list) for g in groups}
    beat = {g: 0 for g in groups}
    # 「全部」包含沒過門檻的流動性差幣，當作「不篩選」的參考；另一組只排除非加密貨幣、不看成交額與振幅
    acc["沒篩選：全部永續（平均）"] = defaultdict(list)
    acc["只排除非加密/新幣，不看成交額與振幅"] = defaultdict(list)
    liq_only = ("成交額", "振幅")
    for s in secs:
        ok = [r for r in s["rows"] if not r["reject"]]
        if len(ok) < K * 2:
            continue
        base_chop = statistics.mean(r["y"]["chop"] for r in ok)
        for y in OUTCOMES:
            acc["全部合格幣（平均）"][y].append(statistics.mean(r["y"][y] for r in ok))
            acc["沒篩選：全部永續（平均）"][y].append(statistics.mean(r["y"][y] for r in s["rows"]))
            crypto = [r for r in s["rows"] if all(any(k in w for k in liq_only) for w in r["reject"])]
            acc["只排除非加密/新幣，不看成交額與振幅"][y].append(statistics.mean(r["y"][y] for r in crypto))
        for g, spec in groups.items():
            if spec is None:
                continue
            _, fn = spec
            key = fn(ok)
            pick = sorted(ok, key=lambda r: -key[id(r)])[:K]
            for y in OUTCOMES:
                acc[g][y].append(statistics.mean(r["y"][y] for r in pick))
            if statistics.mean(r["y"]["chop"] for r in pick) < base_chop:
                beat[g] += 1
    n = len(acc["全部合格幣（平均）"]["chop"])
    if not quiet:
        print(f"{out['period'][0]} → {out['period'][1]}，{n} 個交易日，每天挑前 {K} 名，量測「隔天」：")
        print(f"{'組別':<28}{'4h ER':>8}{'盤整率':>8}{'4h淨移動':>9}{'日振幅':>8}{'盤整少於平均的天數':>12}")
    for g in acc:
        row = {y: statistics.mean(acc[g][y]) for y in OUTCOMES}
        row["days_less_chop"] = beat.get(g)
        out["groups"][g] = row
        if not quiet:
            b = f"{beat[g]}/{n}" if g in beat and groups.get(g) else ""
            print(f"{g:<28}{row['er4h']:>8.3f}{row['chop'] * 100:>7.1f}%{row['move4h']:>8.2f}%{row['rng']:>7.1f}%{b:>12}")
    return out


def cmd_intraday(a, cfg) -> dict:
    """盤中：上一個 4 小時區塊的狀態 → 下一個 4 小時區塊；時段與星期效應。只用合格幣。"""
    panel = load_panel()
    secs = build(panel, cfg, a.date_from, a.until)
    ok_by_day = {s["date"]: {r["sym"] for r in s["rows"] if not r["reject"]} for s in secs}
    chop_er = cfg["chop_er"]
    by_slot = defaultdict(lambda: [0, 0, 0.0])      # 區塊 k：[n, chop 數, ER 合計]
    by_wd = defaultdict(lambda: [0, 0, 0.0])
    trans = defaultdict(lambda: [0, 0, 0.0])         # (前一塊狀態) -> 下一塊
    for date, syms in ok_by_day.items():
        nxt = ymd(to_ms(date) + sc.DAY_MS)
        wd = datetime.strptime(nxt, "%Y-%m-%d").weekday()
        for s in syms:
            days = panel[s]
            d0, d1 = days.get(date), days.get(nxt)
            if not d1:
                continue
            usual = statistics.median(b[2] for d in [days.get(ymd(to_ms(date) - i * sc.DAY_MS)) for i in range(14)]
                                      if d for b in d["blocks"])
            seq = ([("p", b) for b in d0["blocks"]] if d0 else []) + [("n", b) for b in d1["blocks"]]
            for i, (tag, b) in enumerate(seq):
                if tag != "n":
                    continue
                chop = b[0] < chop_er
                for key, store in ((b[4], by_slot), (wd, by_wd)):
                    store[key][0] += 1
                    store[key][1] += chop
                    store[key][2] += b[0]
                if i == 0:
                    continue
                pb = seq[i - 1][1]
                if pb[4] != (b[4] - 1) % 6:
                    continue
                exp = pb[2] / usual if usual else 1
                st = ("CHOP" if pb[0] < chop_er else
                      "TREND" if pb[0] >= cfg["trend_er"] and exp >= 1.0 else
                      "SQUEEZE" if exp < cfg["squeeze_ratio"] else "DRIFT")
                for key in (st, "ALL"):
                    trans[key][0] += 1
                    trans[key][1] += chop
                    trans[key][2] += b[0]
    fmt = lambda v: f"n={v[0]:>7}  盤整率 {v[1] / v[0] * 100:5.1f}%  平均 ER {v[2] / v[0]:.3f}"  # noqa: E731
    print("\n下一個 4 小時區塊，依上一個區塊的狀態（即時模式 now 的分類）：")
    for k in ("ALL", "TREND", "DRIFT", "SQUEEZE", "CHOP"):
        if trans[k][0]:
            print(f"  {k:<8}{fmt(trans[k])}")
    print("\n依 UTC 時段（台北 = UTC+8）：")
    for k in range(6):
        v = by_slot[k]
        if v[0]:
            print(f"  UTC {k * 4:02d}-{k * 4 + 4:02d}（台北 {(k * 4 + 8) % 24:02d}-{(k * 4 + 12) % 24:02d}）  {fmt(v)}")
    print("\n依星期（UTC）：")
    names = "一二三四五六日"
    for k in range(7):
        v = by_wd[k]
        if v[0]:
            print(f"  星期{names[k]}  {fmt(v)}")
    pack = lambda d: {str(k): {"n": v[0], "chop": round(v[1] / v[0], 4), "er": round(v[2] / v[0], 4)}  # noqa: E731
                      for k, v in d.items() if v[0]}
    return {"transition": pack(trans), "slot_utc4h": pack(by_slot), "weekday": pack(by_wd)}


def cmd_gates(a, cfg) -> dict:
    """門檻的效果：只看加密貨幣（排除穩定幣、非加密、新幣），依成交額中位數、日振幅分組，看隔天盤整率。"""
    panel = load_panel()
    secs = build(panel, cfg, a.date_from, a.until)
    other = ("成交額", "振幅")
    qv_edges = [0, 2e6, 5e6, 1e7, 2e7, 5e7, 1e8, 3e8, float("inf")]
    rg_edges = [0, 2, 3, 4, 6, 9, 15, 25, float("inf")]
    qv_b = defaultdict(lambda: [0, 0.0, 0.0])
    rg_b = defaultdict(lambda: [0, 0.0, 0.0])
    for s in secs:
        for r in s["rows"]:
            if not all(any(k in w for k in other) for w in r["reject"]):
                continue
            m, y = r["metrics"], r["y"]
            for edges, store, v in ((qv_edges, qv_b, m["qv_med"]), (rg_edges, rg_b, m["range_pct"])):
                i = next(i for i in range(len(edges) - 1) if edges[i] <= v < edges[i + 1])
                store[i][0] += 1
                store[i][1] += y["chop"]
                store[i][2] += y["move4h"]
    out = {"qv": {}, "range": {}}
    print("隔天盤整率，依過去 14 天日成交額中位數（只看加密貨幣，不套成交額與振幅門檻）：")
    for i in sorted(qv_b):
        n, c, mv = qv_b[i]
        lab = f"{qv_edges[i] / 1e6:g}M – {qv_edges[i + 1] / 1e6:g}M"
        out["qv"][lab] = {"n": n, "chop": round(c / n, 4), "move4h": round(mv / n, 3)}
        print(f"  {lab:<18}n={n:>6}  盤整率 {c / n * 100:5.1f}%  4h 淨移動 {mv / n:.2f}%")
    print("依過去 14 天平均日振幅：")
    for i in sorted(rg_b):
        n, c, mv = rg_b[i]
        lab = f"{rg_edges[i]:g}% – {rg_edges[i + 1]:g}%"
        out["range"][lab] = {"n": n, "chop": round(c / n, 4), "move4h": round(mv / n, 3)}
        print(f"  {lab:<18}n={n:>6}  盤整率 {c / n * 100:5.1f}%  4h 淨移動 {mv / n:.2f}%")
    return out


# ----------------------------------------------------------------------------------------------
# 前向驗證：排程每天跑 scan --news --log（＋AI 的 ai_report.json），之後用歷史資料庫量測「之後 24 小時」
# 事前登記的條件：references/intraday-screener-protocol.md「新聞催化劑的前向驗證」
# ----------------------------------------------------------------------------------------------

FORWARD_MIN_DAYS = 60


def _archive_bars(sym: str, day: str) -> list | None:
    """某個合約某天的 15 分鐘 K（快取在 CACHE/forward/）。還沒發布回傳 None，不存在回傳 []。"""
    d = CACHE / "forward"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sym.encode('ascii', 'backslashreplace').decode().replace(chr(92), '_')}-{day}.json"
    if f.exists():
        return json.loads(f.read_text())
    bars = sc.archive_klines(sym, day)
    if bars is None:
        return None
    f.write_text(json.dumps(bars))
    return bars


def forward_outcome(row: dict, t0: int, cfg: dict) -> dict | None:
    """t0 之後 24 小時的結果（Binance 歷史資料庫）。Bybit / OKX 的幣用同名的 Binance 合約量測。"""
    cands = [row["symbol"]] if row.get("exchange") in ("binance", "archive") and row.get("symbol") else []
    cands += [f"{row['coin']}USDT", f"1000{row['coin']}USDT"]
    days = sorted({ymd(t0 // sc.DAY_MS * sc.DAY_MS), ymd((t0 + sc.DAY_MS - 1) // sc.DAY_MS * sc.DAY_MS)})
    for sym in dict.fromkeys(cands):
        got = [_archive_bars(sym, d) for d in days]
        if any(g is None for g in got):
            continue
        bars = sorted(b for g in got for b in g if t0 <= b[0] < t0 + sc.DAY_MS)
        st = sc.chunk_stats(bars, t0)
        if st and len(st["blocks"]) >= 5:
            bl = st["blocks"]
            return {"er4h": sum(b[0] for b in bl) / len(bl), "chop": sum(b[0] < cfg["chop_er"] for b in bl) / len(bl),
                    "move4h": sum(b[1] for b in bl) / len(bl), "rng": st["rng"]}
    return None


def load_runs(root: Path) -> list[dict]:
    """每個 UTC 日期取最早的一次 scan（避免同一天重複計算），附上同目錄的 ai_report.json（若有）。"""
    runs = []
    for day in sorted(p for p in root.glob("20*-*-*") if p.is_dir()):
        scans = sorted(day.glob("scan-*Z.json"))
        if not scans:
            continue
        res = json.loads(scans[0].read_text(encoding="utf-8"))
        ai = day / "ai_report.json"
        res["_ai"] = json.loads(ai.read_text(encoding="utf-8")) if ai.exists() else None
        res["_file"] = str(scans[0])
        runs.append(res)
    return runs


def cmd_forward(a, cfg) -> dict:
    root = Path(a.log).expanduser()
    runs = load_runs(root)
    now = datetime.now(timezone.utc).timestamp() * 1000
    groups = ["全部合格", "篩選器前 10", "有 24h 內新聞", "沒有新聞", "程式標記：焦點", "AI：焦點", "AI：避開"]
    per_day = {g: defaultdict(list) for g in groups}
    beat = {g: [0, 0] for g in groups}
    pending = done = 0
    for res in runs:
        t0 = to_ms(res["data_until_utc"][:10]) + int(res["data_until_utc"][11:13]) * 3_600_000 + \
            int(res["data_until_utc"][14:16]) * 60_000
        if t0 + sc.DAY_MS > now:  # 之後 24 小時還沒走完
            pending += 1
            continue
        rows = res["watchlist"] + res["bench"]
        ys = {r["coin"]: forward_outcome(r, t0, cfg) for r in rows}
        rows = [r for r in rows if ys.get(r["coin"])]
        if len(rows) < 10:
            if t0 + 4 * sc.DAY_MS > now:  # 歷史資料庫通常隔天發布，偶爾延遲
                pending += 1
            continue
        done += 1
        ai = res.get("_ai") or {}
        ai_focus = {c.upper() for c in ai.get("focus", [])}
        ai_avoid = {c.upper() for c in ai.get("avoid", [])}
        top = {r["coin"] for r in sorted(rows, key=lambda r: -r.get("score", 0))[:10]}
        members = {
            "全部合格": rows,
            "篩選器前 10": [r for r in rows if r["coin"] in top],
            "有 24h 內新聞": [r for r in rows if (r.get("news") or {}).get("n_fresh", 0) > 0],
            "沒有新聞": [r for r in rows if not r.get("news")],
            "程式標記：焦點": [r for r in rows if (r.get("news") or {}).get("tag") == "FOCUS"],
            "AI：焦點": [r for r in rows if r["coin"] in ai_focus],
            "AI：避開": [r for r in rows if r["coin"] in ai_avoid],
        }
        base_chop = statistics.mean(ys[r["coin"]]["chop"] for r in rows)
        for g, rs in members.items():
            if not rs:
                continue
            for y in OUTCOMES:
                per_day[g][y].append(statistics.mean(ys[r["coin"]][y] for r in rs))
            beat[g][1] += 1
            beat[g][0] += statistics.mean(ys[r["coin"]]["chop"] for r in rs) < base_chop
    out = {"runs": len(runs), "evaluated_days": done, "pending": pending, "groups": {}}
    print(f"紀錄 {len(runs)} 天（{root}）：已量測 {done} 天，等待歷史資料 {pending} 天。")
    print(f"{'組別':<16}{'天數':>5}{'盤整率':>8}{'4h淨移動':>9}{'4h ER':>7}{'盤整少於合格平均':>14}")
    for g in groups:
        if not per_day[g]["chop"]:
            print(f"{g:<16}{0:>5}  （沒有資料）")
            continue
        row = {y: statistics.mean(per_day[g][y]) for y in OUTCOMES}
        row.update(days=len(per_day[g]["chop"]), days_less_chop=beat[g][0])
        out["groups"][g] = row
        print(f"{g:<16}{row['days']:>5}{row['chop'] * 100:>7.1f}%{row['move4h']:>8.2f}%{row['er4h']:>7.3f}"
              f"{beat[g][0]:>8}/{beat[g][1]}")
    # 事前登記的判定（樣本夠才判）
    verdicts = {}
    base = out["groups"].get("全部合格")
    for g, key in (("程式標記：焦點", "N"), ("AI：焦點", "A")):
        r = out["groups"].get(g)
        if not r or not base or r["days"] < FORWARD_MIN_DAYS:
            verdicts[g] = f"樣本不足（{r['days'] if r else 0}/{FORWARD_MIN_DAYS} 天），只描述、不判定"
            continue
        h1 = r["chop"] < base["chop"] and r["days_less_chop"] >= 0.55 * r["days"]
        h2 = r["move4h"] >= base["move4h"]
        verdicts[g] = (f"H{key}1 少盤整：{'通過' if h1 else '未通過'}；H{key}2 動得多：{'通過' if h2 else '未通過'}"
                       + ("→ 可以登記新版本、給催化劑權重，再前向驗證一次" if h1 and h2 else "→ 權重維持 0"))
    out["verdicts"] = verdicts
    print("\n判定（references/intraday-screener-protocol.md「新聞催化劑的前向驗證」）：")
    for g, v in verdicts.items():
        print(f"  {g}：{v}")
    print("注意：這裡的「全部合格」是排程當天的合格幣，和保留期研究的 36.7% 不是同一批日子，不能直接比。")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("download")
    p.add_argument("--start", default="2025-11")
    p.add_argument("--end", default="2026-10")
    p.add_argument("--daily-tail", action="store_true")
    p.add_argument("--workers", type=int, default=16)
    for name in ("factors", "evaluate", "intraday", "gates"):
        p = sub.add_parser(name)
        p.add_argument("--from", dest="date_from", default="2025-11-15")
        p.add_argument("--until", default="2026-11-15")
        p.add_argument("--k", type=int, default=10)
        p.add_argument("--config")
        p.add_argument("--json")
    p = sub.add_parser("forward")
    p.add_argument("--log", default=str(Path.home() / ".intraday-screener" / "runs"))
    p.add_argument("--config")
    p.add_argument("--json")
    a = ap.parse_args()
    if a.cmd == "download":
        return cmd_download(a)
    cfg = sc.load_config(a.config)
    res = {"factors": cmd_factors, "evaluate": cmd_evaluate, "intraday": cmd_intraday, "gates": cmd_gates,
           "forward": cmd_forward}[a.cmd](a, cfg)
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
