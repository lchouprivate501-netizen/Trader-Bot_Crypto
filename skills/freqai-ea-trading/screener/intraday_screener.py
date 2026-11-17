#!/usr/bin/env python3
"""全網加密貨幣日內交易篩選器（USDT 永續合約；只用 Python 標準函式庫、只讀公開行情、不需金鑰）。

目的：每天挑出「流動性夠、波動夠、而且走勢常常是一路走而不是來回洗」的幣，
降低「一進場就開始盤整」的機率。三層：

  1. 硬性門檻（不合格直接剔除）：成交額、上市天數、穩定幣、波動區間；即時模式另看買賣價差與
     一筆 impact_notional_usdt 市價單的滑價。
  2. 分數（在合格的幣之間排百分位）：趨勢性（4 小時區塊效率比 ER、盤整比例、變異數比 VR）、
     波動（日內振幅）、熱度（相對成交額 RVOL）、流動性。權重與理由見 config.json 與
     references/intraday-screener.md（權重只用研發期資料決定，保留期驗證一次）。
  3. 即時狀態（now）：觀察清單中的幣「現在」是在走趨勢、在擴張，還是在盤整。

資料來源（--exchange）：
  binance  Binance USDT-M 永續（fapi.binance.com）
  bybit    Bybit USDT 永續（api.bybit.com, category=linear）
  okx      OKX USDT 永續（www.okx.com, SWAP）
  all      以上三家合併（同一個幣：成交額相加，指標用成交額最大的那家計算）
  archive  Binance 公開歷史資料庫 data.binance.vision（交易所 API 被擋時用；資料到昨天為止，
           沒有價差、滑價、資金費）

用法：
  python3 intraday_screener.py scan                       # 今天的觀察清單（Binance）
  python3 intraday_screener.py scan --exchange all --top 20
  python3 intraday_screener.py scan --exchange archive     # 連不到交易所時
  python3 intraday_screener.py now SOL DOGE SUI            # 這幾個幣現在的盤勢
  python3 intraday_screener.py scan --json out.json --html out.html

不是投資建議，不保證不會遇到盤整：驗證結果（降低多少、哪些時段比較糟）見
references/intraday-screener.md。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BAR_MS = 15 * 60 * 1000
HOUR_MS = 3600 * 1000
BLOCK_MS = 4 * HOUR_MS
DAY_MS = 24 * HOUR_MS
BARS_PER_DAY = DAY_MS // BAR_MS          # 96
MIN_BARS_PER_DAY = 90                    # 少於這個數（停機、剛上市）就當作缺資料
UA = "intraday-screener/1.0 (public market data)"

# 穩定幣、法幣、黃金代幣：不是日內波動標的
PEGGED = {
    "USDC", "USDT", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "USDE", "PYUSD", "USD1", "RLUSD", "BFUSD",
    "USDS", "XUSD", "EUR", "EURI", "AEUR", "GBP", "TRY", "BRL", "PAXG", "XAUT", "USTC", "FRAX", "LUSD",
}
# 指數類合約（不是單一幣）與股票 / ETF / 商品 / 外匯永續（non_crypto.json 有產生方式）
INDEX_PRODUCTS = {"BTCDOM", "DEFI", "FOOTBALL", "BLUEBIRD", "USDEX"}
NON_CRYPTO = set(json.loads((HERE / "non_crypto.json").read_text(encoding="utf-8"))["tickers"]) | INDEX_PRODUCTS
SCALE_PREFIX = re.compile(r"^(1000000|100000|10000|1000|1M)(?=[A-Z])")


def base_key(base: str) -> str:
    """1000PEPE / 1000000MOG / 1MBABYDOGE -> PEPE / MOG / BABYDOGE（合併各交易所用）。"""
    return SCALE_PREFIX.sub("", base.upper())


# ----------------------------------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------------------------------

def load_config(path: str | None = None) -> dict:
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    if path:
        user = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


# ----------------------------------------------------------------------------------------------
# 指標：每 24 小時一段的統計（研究與篩選共用同一個函式）
# ----------------------------------------------------------------------------------------------

def chunk_stats(bars: list, start_ms: int) -> dict | None:
    """一段 24 小時（15 分鐘 K 線 [ts, o, h, l, c, quote_volume]，ts 在 [start, start+24h)）。

    回傳：
      o h l c qv          這段的開高低收、成交額（USDT）
      chg                 漲跌 %
      rng                 振幅 (H-L)/O，%
      tr                  15 分鐘 K 線平均真實波幅，%
      er                  整天的效率比 |C-O| / 價格走過的路徑長
      body                |C-O| / (H-L)
      s1 s4 s16           15 分鐘 / 1 小時 / 4 小時對數報酬平方和（算變異數比用）
      blocks              6 個 4 小時區塊：[效率比 ER, 淨移動 %, 振幅 %, 成交額, 區塊序號 0-5]
      hr                  24 個 1 小時對數報酬（算和 BTC 的相關）
    """
    if len(bars) < MIN_BARS_PER_DAY:
        return None
    o = bars[0][1]
    if o <= 0:
        return None
    prev = o
    h = l = None
    qv = path = s1 = tr = 0.0
    nb = 6
    b_ref = [None] * nb
    b_last = [None] * nb
    b_hi = [-math.inf] * nb
    b_lo = [math.inf] * nb
    b_path = [0.0] * nb
    b_qv = [0.0] * nb
    h_ref = [None] * 24
    h_last = [None] * 24
    for ts, bo, bh, bl, bc, bq in bars:
        if bc <= 0 or bl <= 0 or prev <= 0:
            return None
        k = int((ts - start_ms) // BLOCK_MS)
        j = int((ts - start_ms) // HOUR_MS)
        if not (0 <= k < nb and 0 <= j < 24):
            continue
        step = abs(bc - prev)
        path += step
        r = math.log(bc / prev)
        s1 += r * r
        tr += (max(bh, prev) - min(bl, prev)) / prev
        h = bh if h is None else max(h, bh)
        l = bl if l is None else min(l, bl)
        qv += bq
        if b_ref[k] is None:
            b_ref[k] = prev
        b_last[k] = bc
        b_hi[k] = max(b_hi[k], bh)
        b_lo[k] = min(b_lo[k], bl)
        b_path[k] += step
        b_qv[k] += bq
        if h_ref[j] is None:
            h_ref[j] = prev
        h_last[j] = bc
        prev = bc
    c = prev
    blocks, s16 = [], 0.0
    for k in range(nb):
        if b_ref[k] is None:
            continue
        net = b_last[k] - b_ref[k]
        er = abs(net) / b_path[k] if b_path[k] > 0 else 0.0
        s16 += math.log(b_last[k] / b_ref[k]) ** 2
        blocks.append([round(er, 4), round(abs(net) / b_ref[k] * 100, 4),
                       round((b_hi[k] - b_lo[k]) / b_ref[k] * 100, 4), round(b_qv[k]), k])
    hr = [round(math.log(h_last[j] / h_ref[j]), 6) if h_ref[j] else None for j in range(24)]
    s4 = sum(x * x for x in hr if x is not None)
    return {
        "o": o, "h": h, "l": l, "c": c, "qv": round(qv),
        "t": start_ms,
        "chg": round((c / o - 1) * 100, 4),
        "rng": round((h - l) / o * 100, 4),
        "tr": round(tr / len(bars) * 100, 5),
        "er": round(abs(c - o) / path, 4) if path > 0 else 0.0,
        "body": round(abs(c - o) / (h - l), 4) if h > l else 0.0,
        "s1": s1, "s4": s4, "s16": s16,
        "blocks": blocks, "hr": hr,
    }


def split_days(bars: list, end_ms: int, n_days: int) -> list:
    """把 K 線切成 n_days 段連續 24 小時（最後一段結束於 end_ms），每段算 chunk_stats；舊→新。"""
    out = []
    starts = [end_ms - (n_days - i) * DAY_MS for i in range(n_days)]
    buckets = {s: [] for s in starts}
    first = starts[0]
    for b in bars:
        if first <= b[0] < end_ms:
            s = first + (b[0] - first) // DAY_MS * DAY_MS
            if s in buckets:
                buckets[s].append(b)
    for s in starts:
        out.append(chunk_stats(sorted(buckets[s]), s))
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _corr(a: list, b: list) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 48:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None


def window_metrics(days: list, cfg: dict, btc_days: list | None = None) -> dict | None:
    """回看期（舊→新，最後一段 = 最近 24 小時）的指標。缺資料的天數超過 2 天就回傳 None。"""
    L = len(days)
    good = [d for d in days if d]
    if L < 4 or len(good) < L - 2 or not days[-1]:
        return None
    chop_er = cfg["chop_er"]
    last = days[-1]
    prior = [d for d in days[:-1] if d]
    qv_med = statistics.median(d["qv"] for d in prior)
    blocks = [b for d in good for b in d["blocks"]]
    recent = [d for d in days[-3:] if d]
    rng = _mean(d["rng"] for d in good)
    s1 = sum(d["s1"] for d in good)
    m = {
        "qv_24h": last["qv"],
        "qv_med": qv_med,
        "rvol": last["qv"] / qv_med if qv_med > 0 else None,
        "range_pct": rng,
        "tr15_pct": _mean(d["tr"] for d in good),
        "er4h": _mean(b[0] for b in blocks),
        "chop_rate": _mean(1.0 if b[0] < chop_er else 0.0 for b in blocks),
        "move4h_pct": _mean(b[1] for b in blocks),
        "er_day": _mean(d["er"] for d in good),
        "body": _mean(d["body"] for d in good),
        "vr1h": sum(d["s4"] for d in good) / s1 if s1 > 0 else None,
        "vr4h": sum(d["s16"] for d in good) / s1 if s1 > 0 else None,
        "expansion": (_mean(d["rng"] for d in recent) / rng) if rng else None,
        "er4h_3d": _mean(b[0] for d in recent for b in d["blocks"]),
        "chg_24h_pct": last["chg"],
        "days": len(good),
    }
    # 週末（UTC 六、日）和平日的振幅、成交額比：股票 / 商品合約週末成交額約平日的 0.1–0.4，加密貨幣多在 0.6 以上
    wk = [d for d in good if datetime.fromtimestamp((d["t"] + DAY_MS // 2) / 1000, timezone.utc).weekday() >= 5]
    wd = [d for d in good if d not in wk]
    if len(wk) >= 2 and len(wd) >= 4:
        r_wd = _mean(d["rng"] for d in wd)
        q_wd = statistics.median(d["qv"] for d in wd)
        m["weekend_range_ratio"] = _mean(d["rng"] for d in wk) / r_wd if r_wd else None
        m["weekend_qv_ratio"] = statistics.median(d["qv"] for d in wk) / q_wd if q_wd else None
    if btc_days:
        a = [x for d in days for x in (d["hr"] if d else [None] * 24)]
        b = [x for d in btc_days for x in (d["hr"] if d else [None] * 24)]
        m["btc_corr"] = _corr(a, b)
    return m


# ----------------------------------------------------------------------------------------------
# 篩選與評分
# ----------------------------------------------------------------------------------------------

def gate(row: dict, cfg: dict) -> list[str]:
    """回傳不合格原因（空 = 合格）。row 需有 metrics；即時模式另有 spread_bps / impact_bps。"""
    why = []
    m = row["metrics"]
    if base_key(row["base"]) in PEGGED:
        why.append("穩定幣/錨定資產")
    if base_key(row["base"]) in NON_CRYPTO or row.get("non_crypto"):
        why.append("不是加密貨幣（指數 / 股票 / ETF / 商品 / 外匯合約）")
    else:  # 備援：清單沒有的新合約，看週末是否像股票一樣冷清
        wr, wq = m.get("weekend_range_ratio"), m.get("weekend_qv_ratio")
        if wr is not None and wq is not None and wq < cfg["weekend_qv_max"] and wr < cfg["weekend_range_max"]:
            why.append(f"週末冷清（成交額 {wq:.2f}、振幅 {wr:.2f} 倍平日）：疑似股票 / 商品合約")
    if row.get("age_days") is not None and row["age_days"] < cfg["min_age_days"]:
        why.append(f"上市 {row['age_days']:.0f} 天 < {cfg['min_age_days']}")
    if m["days"] < cfg["lookback_days"] - 2:
        why.append("資料天數不足")
    if m["qv_med"] < cfg["min_median_qv_usdt"]:
        why.append(f"日成交額中位數 {m['qv_med'] / 1e6:.1f}M < {cfg['min_median_qv_usdt'] / 1e6:.0f}M")
    qv24 = row.get("qv_total_24h", m["qv_24h"])
    if qv24 < cfg["min_qv_24h_usdt"]:
        why.append(f"24h 成交額 {qv24 / 1e6:.1f}M < {cfg['min_qv_24h_usdt'] / 1e6:.0f}M")
    if m["range_pct"] < cfg["min_range_pct"]:
        why.append(f"日振幅 {m['range_pct']:.1f}% < {cfg['min_range_pct']}%")
    if m["range_pct"] > cfg["max_range_pct"]:
        why.append(f"日振幅 {m['range_pct']:.1f}% > {cfg['max_range_pct']}%（過熱）")
    if row.get("spread_bps") is not None and row["spread_bps"] > cfg["max_spread_bps"]:
        why.append(f"價差 {row['spread_bps']:.1f}bp > {cfg['max_spread_bps']}bp")
    if row.get("impact_bps") is not None and row["impact_bps"] > cfg["max_impact_bps"]:
        why.append(f"{cfg['impact_notional_usdt'] / 1e3:.0f}k 市價單滑價 {row['impact_bps']:.1f}bp > {cfg['max_impact_bps']}bp")
    if row.get("impact_bps") is None and row.get("book_checked"):
        why.append("掛單簿深度不足")
    return why


def pct_ranks(values: list) -> list:
    """百分位（0 = 最小、1 = 最大），None 給 0.5。同值取平均名次。"""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [0.5] * len(values)
    if len(idx) < 2:
        return out
    order = sorted(idx, key=lambda i: values[i])
    n = len(order)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2 / (n - 1)
        for t in range(i, j + 1):
            out[order[t]] = r
        i = j + 1
    return out


FACTORS = {
    # 名稱: (取值（越大越好）, 說明)。research.py 用同一張表檢驗每個因子對「隔天」的預測力。
    "er4h": (lambda m: m["er4h"], "4h 區塊效率比"),
    "anti_chop": (lambda m: -m["chop_rate"], "−盤整率"),
    "vr4h": (lambda m: m["vr4h"], "4h 變異數比"),
    "vr1h": (lambda m: m["vr1h"], "1h 變異數比"),
    "er_day": (lambda m: m["er_day"], "整天效率比"),
    "body": (lambda m: m["body"], "日 K 實體比"),
    "er4h_3d": (lambda m: m["er4h_3d"], "近 3 天 4h ER"),
    "range": (lambda m: m["range_pct"], "日振幅"),
    "tr15": (lambda m: m["tr15_pct"], "15m ATR%"),
    "move4h": (lambda m: m["move4h_pct"], "4h 淨移動%"),
    "rvol": (lambda m: math.log(m["rvol"]) if m.get("rvol") else None, "相對成交額"),
    "expansion": (lambda m: m["expansion"], "振幅擴張 3天/14天"),
    "liquidity": (lambda m: math.log(m["qv_med"]) if m["qv_med"] > 0 else None, "成交額中位數"),
    "abs_chg": (lambda m: abs(m["chg_24h_pct"]), "|24h 漲跌|"),
}


def factor_values(m: dict, names) -> dict:
    return {k: FACTORS[k][0](m) for k in names}


def score_rows(rows: list, cfg: dict) -> None:
    """合格的幣之間排百分位，依 cfg['weights'] 加權成 0-100 分。就地寫入 row['score']、row['factors']。"""
    w = cfg["weights"]
    ok = [r for r in rows if not r["reject"]]
    if not ok:
        return
    w = {k: v for k, v in w.items() if not k.startswith("_") and v}
    fv = [factor_values(r["metrics"], w) for r in ok]
    total = sum(abs(x) for x in w.values()) or 1.0
    ranks = {k: pct_ranks([f[k] for f in fv]) for k in w}
    for i, r in enumerate(ok):
        r["factors"] = {k: round(ranks[k][i] * 100) for k in w}
        r["score"] = round(sum(w[k] * ranks[k][i] for k in w) / total * 100, 1)


# ----------------------------------------------------------------------------------------------
# 即時盤勢（now）
# ----------------------------------------------------------------------------------------------

def intraday_state(bars: list, days: list, cfg: dict) -> dict:
    """最近 4 小時 / 1 小時的盤勢，對照回看期的 4 小時區塊。bars：最近的 15 分鐘 K 線（舊→新）。"""
    blocks = [b for d in days if d for b in d["blocks"]]
    last16 = bars[-17:]
    ref = last16[0][4]
    path = sum(abs(last16[i][4] - last16[i - 1][4]) for i in range(1, len(last16)))
    net = last16[-1][4] - ref
    er = abs(net) / path if path > 0 else 0.0
    hi = max(b[2] for b in last16[1:])
    lo = min(b[3] for b in last16[1:])
    rng4 = (hi - lo) / ref * 100
    med_rng4 = statistics.median(b[2] for b in blocks) if blocks else None
    last4 = bars[-5:]
    rng1 = (max(b[2] for b in last4[1:]) - min(b[3] for b in last4[1:])) / last4[0][4] * 100
    pos = (bars[-1][4] - lo) / (hi - lo) if hi > lo else 0.5
    exp = rng4 / med_rng4 if med_rng4 else None
    # 只描述「剛剛」發生什麼。驗證結果：這個分類無法預測下一個 4 小時會不會盤整（見 intraday-screener.md）
    if er < cfg["chop_er"]:
        state = "CHOP"
        note = "最近 4 小時來回洗"
    elif er >= cfg["trend_er"] and (exp or 0) >= 1.0:
        state = "TREND_UP" if net > 0 else "TREND_DOWN"
        note = "最近 4 小時單邊" + ("上漲" if net > 0 else "下跌") + "、振幅不低於平常"
    elif (exp or 0) < cfg["squeeze_ratio"]:
        state = "SQUEEZE"
        note = "最近 4 小時振幅不到平常一半"
    else:
        state = "DRIFT_UP" if net > 0 else "DRIFT_DOWN"
        note = "有方向、力道普通"
    return {
        "state": state, "note": note, "er_4h": round(er, 3), "move_4h_pct": round(net / ref * 100, 2),
        "range_4h_pct": round(rng4, 2), "range_vs_usual": round(exp, 2) if exp else None,
        "range_1h_pct": round(rng1, 2), "pos_in_4h_range": round(pos, 2), "last": bars[-1][4],
        "usual_er4h": round(_mean(b[0] for b in blocks), 3) if blocks else None,
    }


# ----------------------------------------------------------------------------------------------
# 資料來源
# ----------------------------------------------------------------------------------------------

class SourceError(RuntimeError):
    pass


class RateLimiter:
    """滑動一分鐘的權重上限（各交易所公開 API 的限速，留安全邊際）。"""

    def __init__(self, per_minute: float):
        self.cap = per_minute
        self.hist: list = []
        self.lock = threading.Lock()

    def take(self, weight: float = 1.0) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.hist = [(t, w) for t, w in self.hist if now - t < 60]
                if sum(w for _, w in self.hist) + weight <= self.cap:
                    self.hist.append((now, weight))
                    return
                wait = 60 - (now - self.hist[0][0]) + 0.05
            time.sleep(max(wait, 0.05))


def http_get(url: str, *, timeout: float = 20, retries: int = 3, raw: bool = False):
    last_err = None
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*[]~")  # 有中文名稱的合約（URL 只能是 ASCII）
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = f"HTTP {e.code}"
            if e.code in (403, 451):  # 地區封鎖：重試沒用
                break
            wait = float(e.headers.get("Retry-After") or 0) if e.code in (418, 429) else 0
            time.sleep(max(wait, 1.5 ** attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = str(getattr(e, "reason", e))
            time.sleep(1.5 ** attempt)
    host = urllib.parse.urlparse(url).netloc
    raise SourceError(f"連不到 {host}（{last_err}）。所在地可能封鎖這家交易所：改用 --exchange bybit / okx，"
                      f"或 --exchange archive（Binance 歷史資料庫，到昨天為止）")


def _book_metrics(bids: list, asks: list, notional: float) -> dict:
    """bids/asks：[(price, base_qty)]，最佳價在前。回傳價差與一筆 notional 市價買/賣的平均滑價（bp，取兩邊較差者）。"""
    if not bids or not asks:
        return {"spread_bps": None, "impact_bps": None, "book_checked": True}
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    out = {"spread_bps": round((ba - bb) / mid * 1e4, 2), "book_checked": True}
    worst = 0.0
    for side, book in (("buy", asks), ("sell", bids)):
        left, cost, qty = notional, 0.0, 0.0
        for p, q in book:
            take = min(left, p * q)
            cost += take
            qty += take / p
            left -= take
            if left <= 1e-9:
                break
        if left > 1e-9:
            out["impact_bps"] = None
            return out
        avg = cost / qty
        worst = max(worst, abs(avg - mid) / mid * 1e4)
    out["impact_bps"] = round(worst, 2)
    return out


class Binance:
    name = "binance"
    BASE = "https://fapi.binance.com"
    workers = 8

    def __init__(self):
        self.limit = RateLimiter(1500)  # 官方 2400 權重 / 分鐘

    def universe(self) -> list[dict]:
        info = http_get(f"{self.BASE}/fapi/v1/exchangeInfo")
        tick = {t["symbol"]: t for t in http_get(f"{self.BASE}/fapi/v1/ticker/24hr")}
        fund = {p["symbol"]: p for p in (http_get(f"{self.BASE}/fapi/v1/premiumIndex") or [])}
        now = time.time() * 1000
        out = []
        for s in info["symbols"]:
            if s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT" or s.get("status") != "TRADING":
                continue
            t = tick.get(s["symbol"])
            if not t:
                continue
            f = fund.get(s["symbol"], {})
            utype = s.get("underlyingType")
            out.append({
                "exchange": self.name, "symbol": s["symbol"], "base": s["baseAsset"],
                "qv_24h": float(t["quoteVolume"]), "last": float(t["lastPrice"]),
                "chg_24h_pct": float(t["priceChangePercent"]),
                "funding": float(f["lastFundingRate"]) if f.get("lastFundingRate") not in (None, "") else None,
                "age_days": (now - s["onboardDate"]) / DAY_MS if s.get("onboardDate") else None,
                "non_crypto": utype not in (None, "", "COIN", "PREMARKET"),  # INDEX、股票、商品…
            })
        return out

    def klines(self, symbol: str, n: int) -> list:
        self.limit.take(10 if n > 1000 else 5)
        data = http_get(f"{self.BASE}/fapi/v1/klines?symbol={symbol}&interval=15m&limit={min(n, 1500)}")
        return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])] for k in data or []]

    def book(self, symbol: str, notional: float) -> dict:
        self.limit.take(10)
        d = http_get(f"{self.BASE}/fapi/v1/depth?symbol={symbol}&limit=500")
        if not d:
            return {"book_checked": True}
        conv = lambda xs: [(float(p), float(q)) for p, q in xs]  # noqa: E731
        return _book_metrics(conv(d["bids"]), conv(d["asks"]), notional)


class Bybit:
    name = "bybit"
    BASE = "https://api.bybit.com"
    workers = 6

    def __init__(self):
        self.limit = RateLimiter(3000)  # 官方 600 次 / 5 秒

    def universe(self) -> list[dict]:
        inst, cursor = [], ""
        for _ in range(10):
            d = http_get(f"{self.BASE}/v5/market/instruments-info?category=linear&limit=1000"
                         + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""))
            inst += d["result"]["list"]
            cursor = d["result"].get("nextPageCursor") or ""
            if not cursor:
                break
        tick = {t["symbol"]: t for t in http_get(f"{self.BASE}/v5/market/tickers?category=linear")["result"]["list"]}
        now = time.time() * 1000
        out = []
        for s in inst:
            if (s.get("contractType") != "LinearPerpetual" or s.get("quoteCoin") != "USDT"
                    or s.get("status") != "Trading"):
                continue
            t = tick.get(s["symbol"])
            if not t:
                continue
            fr = t.get("fundingRate")
            out.append({
                "exchange": self.name, "symbol": s["symbol"], "base": s["baseCoin"],
                "qv_24h": float(t.get("turnover24h") or 0), "last": float(t["lastPrice"]),
                "chg_24h_pct": float(t.get("price24hPcnt") or 0) * 100,
                "funding": float(fr) if fr not in (None, "") else None,
                "age_days": (now - int(s["launchTime"])) / DAY_MS if s.get("launchTime") else None,
            })
        return out

    def klines(self, symbol: str, n: int) -> list:
        rows, end = {}, None
        while len(rows) < n:
            self.limit.take()
            url = f"{self.BASE}/v5/market/kline?category=linear&symbol={symbol}&interval=15&limit=1000"
            if end:
                url += f"&end={end}"
            lst = (http_get(url) or {}).get("result", {}).get("list") or []
            if not lst:
                break
            for k in lst:  # 新→舊；[start, o, h, l, c, volume, turnover]
                rows[int(k[0])] = [int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[6])]
            oldest = min(int(k[0]) for k in lst)
            if end is not None and oldest >= end:
                break
            end = oldest - 1
            if len(lst) < 1000:
                break
        return [rows[t] for t in sorted(rows)][-n:]

    def book(self, symbol: str, notional: float) -> dict:
        self.limit.take()
        d = (http_get(f"{self.BASE}/v5/market/orderbook?category=linear&symbol={symbol}&limit=500") or {}).get("result")
        if not d:
            return {"book_checked": True}
        conv = lambda xs: [(float(p), float(q)) for p, q in xs]  # noqa: E731
        return _book_metrics(conv(d.get("b", [])), conv(d.get("a", [])), notional)


class OKX:
    name = "okx"
    BASE = "https://www.okx.com"
    workers = 2

    def __init__(self):
        self.ct_val: dict[str, float] = {}
        self.limit = RateLimiter(480)  # history-candles 官方 20 次 / 2 秒

    def universe(self) -> list[dict]:
        inst = http_get(f"{self.BASE}/api/v5/public/instruments?instType=SWAP")["data"]
        tick = {t["instId"]: t for t in http_get(f"{self.BASE}/api/v5/market/tickers?instType=SWAP")["data"]}
        now = time.time() * 1000
        out = []
        for s in inst:
            if s.get("settleCcy") != "USDT" or s.get("state") != "live" or s.get("ctType") != "linear":
                continue
            t = tick.get(s["instId"])
            if not t:
                continue
            self.ct_val[s["instId"]] = float(s.get("ctVal") or 1)
            last = float(t["last"])
            op = float(t.get("sodUtc0") or t.get("open24h") or last)
            base = s["instId"].split("-")[0]
            out.append({
                "exchange": self.name, "symbol": s["instId"], "base": base,
                "qv_24h": float(t.get("volCcy24h") or 0) * last,   # SWAP 的 volCcy24h 以幣計
                "last": last, "chg_24h_pct": (last / float(t.get("open24h") or op) - 1) * 100 if last else 0.0,
                "funding": None,
                "age_days": (now - int(s["listTime"])) / DAY_MS if s.get("listTime") else None,
            })
        return out

    def klines(self, symbol: str, n: int) -> list:
        rows, after = {}, None
        for _ in range(n // 100 + 3):
            path = "candles" if after is None else "history-candles"
            url = f"{self.BASE}/api/v5/market/{path}?instId={symbol}&bar=15m&limit={300 if after is None else 100}"
            if after:
                url += f"&after={after}"
            self.limit.take()
            lst = (http_get(url) or {}).get("data") or []
            if not lst:
                break
            for k in lst:  # 新→舊；[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
                if len(k) > 8 and k[8] == "0":
                    continue  # 還沒收盤
                rows[int(k[0])] = [int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])]
            after = min(int(k[0]) for k in lst)
            if len(rows) >= n:
                break
        return [rows[t] for t in sorted(rows)][-n:]

    def book(self, symbol: str, notional: float) -> dict:
        self.limit.take()
        d = (http_get(f"{self.BASE}/api/v5/market/books?instId={symbol}&sz=400") or {}).get("data")
        if not d:
            return {"book_checked": True}
        cv = self.ct_val.get(symbol, 1.0)
        conv = lambda xs: [(float(x[0]), float(x[1]) * cv) for x in xs]  # noqa: E731
        return _book_metrics(conv(d[0].get("bids", [])), conv(d[0].get("asks", [])), notional)


ARCHIVE = "https://data.binance.vision/data/futures/um"
ARCHIVE_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def archive_symbols(kind: str = "daily") -> list[str]:
    """data.binance.vision 上所有 USDT 永續（含已下架）的代號。"""
    out, marker = [], ""
    pat = re.compile(rf"<Prefix>data/futures/um/{kind}/klines/([^<]+)/</Prefix>")
    for _ in range(20):
        q = f"?delimiter=/&prefix=data/futures/um/{kind}/klines/" + (f"&marker={urllib.parse.quote(marker)}" if marker else "")
        xml = http_get(ARCHIVE_LIST + q, raw=True).decode()
        out += pat.findall(xml)
        m = re.search(r"<NextMarker>([^<]+)</NextMarker>", xml)
        if "<IsTruncated>true</IsTruncated>" not in xml or not m:
            break
        marker = m.group(1)
    return sorted({s for s in out if s.endswith("USDT") and "_" not in s})


def archive_klines(symbol: str, period: str, interval: str = "15m") -> list | None:
    """period：'YYYY-MM'（月檔）或 'YYYY-MM-DD'（日檔）。沒有檔案回傳 None。"""
    kind = "monthly" if len(period) == 7 else "daily"
    raw = http_get(f"{ARCHIVE}/{kind}/klines/{symbol}/{interval}/{symbol}-{interval}-{period}.zip", raw=True, timeout=60)
    if raw is None:
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        text = zf.read(zf.namelist()[0]).decode()
    rows = []
    for rec in csv.reader(io.StringIO(text)):
        if not rec or not rec[0].isdigit():
            continue
        ts = int(rec[0])
        if ts > 10**14:
            ts //= 1000
        rows.append([ts, float(rec[1]), float(rec[2]), float(rec[3]), float(rec[4]), float(rec[7])])
    return rows


class Archive:
    """Binance 公開歷史資料庫：沒有即時價、掛單簿、資金費；最新資料是昨天（UTC）收盤。"""
    name = "archive"
    workers = 8

    def __init__(self, lookback_days: int, workers: int = 16):
        self.workers = workers
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.end_ms = int(today.timestamp() * 1000)
        self.lookback = lookback_days
        self._cache: dict[str, list] = {}
        self._probe_day = None

    def _day(self, ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")

    def universe(self) -> list[dict]:
        syms = archive_symbols("daily")
        # 找最近一個已發布的日檔（通常是昨天；偶爾延遲一天）
        for back in (1, 2, 3):
            day_ms = self.end_ms - back * DAY_MS
            if archive_klines("BTCUSDT", self._day(day_ms)):
                break
        else:
            raise SourceError("data.binance.vision 最近三天都沒有日檔")
        self.end_ms = day_ms + DAY_MS
        self._probe_day = self._day(day_ms)
        with ThreadPoolExecutor(self.workers) as pool:
            got = list(pool.map(lambda s: (s, archive_klines(s, self._probe_day)), syms))
        out = []
        for s, bars in got:
            if not bars:
                continue  # 已下架或這天沒交易
            self._cache[s] = bars
            out.append({"exchange": self.name, "symbol": s, "base": s[:-4],
                         "qv_24h": sum(b[5] for b in bars), "last": bars[-1][4],
                         "chg_24h_pct": (bars[-1][4] / bars[0][1] - 1) * 100, "funding": None, "age_days": None})
        return out

    def klines(self, symbol: str, n: int) -> list:
        days = math.ceil(n / BARS_PER_DAY)
        names = [self._day(self.end_ms - (i + 1) * DAY_MS) for i in range(days)]
        rows = list(self._cache.get(symbol, []))
        need = [d for d in names if d != self._probe_day]
        with ThreadPoolExecutor(4) as pool:
            for bars in pool.map(lambda d: archive_klines(symbol, d), need):
                rows += bars or []
        rows = sorted({r[0]: r for r in rows}.values())
        return rows[-n:]

    def book(self, symbol: str, notional: float) -> dict:
        return {}


SOURCES = {"binance": Binance, "bybit": Bybit, "okx": OKX}


# ----------------------------------------------------------------------------------------------
# 掃描
# ----------------------------------------------------------------------------------------------

def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, file=sys.stderr, flush=True)


def _analyse(src, item: dict, cfg: dict, n_bars: int, end_ms: int | None, btc_days) -> dict:
    bars = src.klines(item["symbol"], n_bars)
    if not bars:
        return {**item, "metrics": None, "reject": ["沒有 K 線"]}
    if end_ms is None:  # 即時：最後一根已收盤 K 線的結束時間
        now = time.time() * 1000
        closed = [b for b in bars if b[0] + BAR_MS <= now]
        end = closed[-1][0] + BAR_MS if closed else bars[-1][0] + BAR_MS
        bars = closed
    else:
        end = end_ms
    days = split_days(bars, end, cfg["lookback_days"])
    m = window_metrics(days, cfg, btc_days)
    row = {**item, "metrics": m, "_days": days, "_bars": bars[-40:], "end_ms": end}
    if m is None:
        row["reject"] = ["資料天數不足"]
    return row


def scan(cfg: dict, exchange: str = "binance", top: int | None = None, symbols: list | None = None,
         quiet: bool = False, workers: int = 8) -> dict:
    """主流程：取宇宙 → 用 24h 成交額預篩 → 抓 K 線算指標 → 硬門檻 → 掛單簿（只看前段班）→ 評分。"""
    top = top or cfg["top"]
    n_bars = cfg["lookback_days"] * BARS_PER_DAY + 8
    names = list(SOURCES) if exchange == "all" else [exchange]
    srcs = [Archive(cfg["lookback_days"]) if n == "archive" else SOURCES[n]() for n in names]
    errors, items = {}, []
    for src in srcs:
        try:
            _log(f"[{src.name}] 讀取合約清單與 24h 行情…", quiet)
            items += [dict(x, _src=src) for x in src.universe()]
        except SourceError as e:
            errors[src.name] = str(e)
            _log(f"[{src.name}] {e}", quiet)
    if not items:
        raise SourceError("所有資料來源都失敗：" + "；".join(errors.values()))

    # 同一個幣在多家：成交額相加，指標用成交額最大的那家
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(base_key(it["base"]), []).append(it)
    merged = []
    for key, its in groups.items():
        its.sort(key=lambda x: -x["qv_24h"])
        best = dict(its[0])
        best["coin"] = key
        best["qv_total_24h"] = sum(x["qv_24h"] for x in its)
        best["venues"] = {x["exchange"]: round(x["qv_24h"]) for x in its}
        merged.append(best)
    btc_item = next((r for r in merged if r["coin"] == "BTC"), None)
    if symbols:
        want = {base_key(s.upper().replace("USDT", "").split("-")[0]) for s in symbols}
        merged = [r for r in merged if r["coin"] in want]
    else:
        merged = [r for r in merged if base_key(r["base"]) not in PEGGED
                  and r["qv_total_24h"] >= cfg["min_qv_24h_usdt"] * cfg["prefilter_ratio"]]
    merged.sort(key=lambda r: -r["qv_total_24h"])
    _log(f"預篩後 {len(merged)} 個幣（24h 成交額 ≥ {cfg['min_qv_24h_usdt'] * cfg['prefilter_ratio'] / 1e6:.0f}M），"
         f"下載 {cfg['lookback_days']} 天 15 分鐘 K 線…", quiet)

    # BTC 當相關性基準
    end_ms = srcs[0].end_ms if isinstance(srcs[0], Archive) else None
    btc_days = None
    if btc_item is not None:
        try:
            btc_days = _analyse(btc_item["_src"], btc_item, cfg, n_bars, end_ms, None).get("_days")
        except SourceError:
            btc_days = None
    sem = {s.name: threading.Semaphore(getattr(s, "workers", workers)) for s in srcs}

    def work(r):
        with sem[r["_src"].name]:
            try:
                return _analyse(r["_src"], r, cfg, n_bars, end_ms, btc_days)
            except SourceError as e:
                return {**r, "metrics": None, "reject": [str(e)]}

    with ThreadPoolExecutor(sum(getattr(s, "workers", workers) for s in srcs)) as pool:
        rows = list(pool.map(work, merged))
    for r in rows:
        if r.get("metrics") and "reject" not in r:
            r["reject"] = gate(r, cfg)
    # 掛單簿：只看還合格的（每個要一次請求）
    live = [r for r in rows if not r["reject"] and not isinstance(r["_src"], Archive)]
    if live:
        _log(f"檢查 {len(live)} 個幣的掛單簿（價差、{cfg['impact_notional_usdt'] / 1e3:.0f}k USDT 市價單滑價）…", quiet)

        def bookwork(r):
            with sem[r["_src"].name]:
                try:
                    r.update(r["_src"].book(r["symbol"], cfg["impact_notional_usdt"]))
                except SourceError:
                    r["book_checked"] = False
            return r
        with ThreadPoolExecutor(sum(getattr(s, "workers", workers) for s in srcs)) as pool:
            list(pool.map(bookwork, live))
        for r in live:
            r["reject"] = gate(r, cfg)
    score_rows(rows, cfg)
    for r in rows:
        r["warnings"] = warnings_for(r, cfg)
    passed = sorted([r for r in rows if not r["reject"]], key=lambda r: -r["score"])
    for r in passed[:top]:
        r["now"] = intraday_state(r["_bars"], r["_days"], cfg)
    requested = []
    if symbols:  # now 指令：不管合不合格都給盤勢
        for r in rows:
            if r.get("metrics") and "now" not in r:
                r["now"] = intraday_state(r["_bars"], r["_days"], cfg)
            requested.append({**(public_row(r) if r.get("metrics") else {"coin": r["coin"]}), "reject": r["reject"]})
    end = max((r.get("end_ms") or 0) for r in rows) if rows else None
    return {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "data_until_utc": datetime.fromtimestamp(end / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M") if end else None,
        "exchange": exchange, "lookback_days": cfg["lookback_days"], "errors": errors,
        "universe": len(items), "analysed": len(rows), "passed": len(passed),
        "watchlist": [public_row(r) for r in passed[:top]],
        "bench": [public_row(r) for r in passed[top:]],
        "rejected": [{"coin": r["coin"], "exchange": r["exchange"], "why": r["reject"]} for r in rows if r["reject"]],
        "requested": requested,
        "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
    }


def warnings_for(r: dict, cfg: dict) -> list[str]:
    m = r.get("metrics")
    w = []
    if not m:
        return w
    if r.get("funding") is not None and abs(r["funding"]) >= cfg["funding_warn"]:
        side = "多方" if r["funding"] > 0 else "空方"
        w.append(f"資金費 {r['funding'] * 100:.3f}%／期：{side}擁擠，容易被反向洗")
    if m.get("rvol") and m["rvol"] >= cfg["rvol_spike"]:
        w.append(f"今天成交額是平常 {m['rvol']:.1f} 倍：有事件，波動可能突然反轉")
    if m["range_pct"] >= cfg["max_range_pct"] * 0.7:
        w.append("振幅接近過熱上限：停損要放寬、部位要縮小")
    if m.get("btc_corr") is not None and m["btc_corr"] >= cfg["btc_corr_warn"] and r.get("coin") != "BTC":
        w.append(f"和 BTC 相關 {m['btc_corr']:.2f}：走勢大致跟著 BTC，先看 BTC")
    return w


def public_row(r: dict) -> dict:
    m = r["metrics"]
    keep = ("coin", "exchange", "symbol", "last", "qv_total_24h", "venues", "funding", "spread_bps", "impact_bps",
            "score", "factors", "warnings", "now", "age_days")
    out = {k: r.get(k) for k in keep if r.get(k) is not None}
    out["metrics"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}
    return out


# ----------------------------------------------------------------------------------------------
# 輸出
# ----------------------------------------------------------------------------------------------

STATE_ZH = {"TREND_UP": "單邊↑", "TREND_DOWN": "單邊↓", "DRIFT_UP": "偏多", "DRIFT_DOWN": "偏空",
            "SQUEEZE": "收斂", "CHOP": "來回洗"}


def _m(x: float) -> str:
    return f"{x / 1e9:.2f}B" if x >= 1e9 else f"{x / 1e6:.0f}M"


def print_table(res: dict, show_bench: int = 10) -> None:
    print(f"\n日內交易觀察清單  {res['exchange']}  資料到 {res['data_until_utc']} UTC  回看 {res['lookback_days']} 天")
    print(f"宇宙 {res['universe']} 個合約 → 分析 {res['analysed']} 個幣 → 合格 {res['passed']} 個")
    if res["errors"]:
        for k, v in res["errors"].items():
            print(f"  ! {k}: {v}")
    hdr = (f"{'#':>2} {'幣':<10}{'分數':>5} {'24h額':>7} {'日振幅':>6} {'4hER':>5} {'盤整率':>6} {'VR':>5} "
           f"{'RVOL':>5} {'滑價':>5} {'近4h':<6} 提醒")
    print(hdr)
    print("-" * len(hdr.encode("utf-8")))
    for i, r in enumerate(res["watchlist"], 1):
        m = r["metrics"]
        imp = f"{r['impact_bps']:.1f}" if r.get("impact_bps") is not None else "-"
        now = STATE_ZH.get(r.get("now", {}).get("state"), "")
        warn = "；".join(w.split("：")[0] for w in r.get("warnings", []))
        print(f"{i:>2} {r['coin']:<10}{r['score']:>5.0f} {_m(r.get('qv_total_24h', m['qv_24h'])):>7} "
              f"{m['range_pct']:>5.1f}% {m['er4h']:>5.3f} {m['chop_rate'] * 100:>5.0f}% {m['vr4h']:>5.2f} "
              f"{m['rvol']:>5.2f} {imp:>5} {now:<6} {warn}")
    if show_bench and res["bench"]:
        print("候補：" + "、".join(f"{r['coin']}({r['score']:.0f})" for r in res["bench"][:show_bench]))
    print("\n欄位：4hER＝4 小時區塊效率比（淨移動 / 走過的路；隨機漫步約 0.25）；盤整率＝ER<門檻的 4 小時區塊比例"
          "（過去 14 天）；VR＝4 小時變異數比（>1 偏趨勢）；RVOL＝最近 24h 成交額 / 平常；滑價＝一筆市價單的平均滑價 bp；"
          "近4h＝剛剛 4 小時的盤勢（描述，不是預測）。")
    print("驗證（Binance 全部 USDT 永續、保留期 2026-06 → 11）：門檻把加密貨幣隔天的盤整率從 49% 降到 37%（主要是"
          "排除死幣與極低流動性的幣）；清單前 10 名隔天每 4 小時的淨移動比合格幣平均大 29%，但盤整率沒有更低"
          "（37.0% vs 36.7%）。約 1/3 的 4 小時會盤整是短線加密貨幣的常態（隨機漫步也有 36%），選幣消不掉。")
    hint = session_hint(res.get("config", {}))
    if hint:
        print(hint)


def session_hint(cfg: dict, at_ms: float | None = None) -> str:
    """現在屬於哪個 UTC 4 小時時段，以及驗證期間該時段的盤整率。"""
    sess = cfg.get("session_chop_pct") or {}
    hour = datetime.fromtimestamp((at_ms or time.time() * 1000) / 1000, timezone.utc).hour
    key = f"{hour // 4 * 4:02d}-{hour // 4 * 4 + 4:02d}"
    cur = sess.get(key)
    rows = {k: v for k, v in sess.items() if not k.startswith("_")}
    if not cur or not rows:
        return ""
    best = min(rows, key=lambda k: sum(rows[k]))
    worst = max(rows, key=lambda k: sum(rows[k]))
    tw = lambda k: f"{(int(k[:2]) + 8) % 24:02d}-{(int(k[:2]) + 12) % 24 or 24:02d}"  # noqa: E731
    return (f"現在是 UTC {key}（台北 {tw(key)}）時段：歷史盤整率 {cur[0]:.1f}% / {cur[1]:.1f}%（研發期 / 保留期）。"
            f"最少盤整 UTC {best}（台北 {tw(best)}）{rows[best][0]:.1f}% / {rows[best][1]:.1f}%；"
            f"最多 UTC {worst}（台北 {tw(worst)}）{rows[worst][0]:.1f}% / {rows[worst][1]:.1f}%。")


def print_now(rows: list, cfg: dict) -> None:
    print(f"\n{'幣':<10}{'近4h':<6} {'4h ER':>6} {'4h 漲跌':>8} {'4h振幅/平常':>11} {'1h振幅':>7}  說明")
    for r in rows:
        n = r["now"]
        rv = f"{n['range_vs_usual']:.2f}x" if n.get("range_vs_usual") else "-"
        print(f"{r['coin']:<10}{STATE_ZH[n['state']]:<6} {n['er_4h']:>6.3f} {n['move_4h_pct']:>7.2f}% {rv:>11} "
              f"{n['range_1h_pct']:>6.2f}%  {n['note']}")
    print("\n注意：「近4h」只描述剛剛發生的事。驗證結果它無法預測下一個 4 小時會不會盤整"
          "（保留期：前 4 小時單邊之後盤整率 37.4%、來回洗之後 35.6%），別把它當進場訊號。")
    hint = session_hint(cfg)
    if hint:
        print(hint)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "now"):
        p = sub.add_parser(name)
        p.add_argument("--exchange", default="binance", choices=["binance", "bybit", "okx", "all", "archive"])
        p.add_argument("--config", help="覆寫設定的 JSON 檔（只寫要改的欄位）")
        p.add_argument("--json", help="結果寫成 JSON")
        p.add_argument("--quiet", action="store_true")
        if name == "scan":
            p.add_argument("--top", type=int)
            p.add_argument("--html", help="結果寫成 HTML 頁")
        else:
            p.add_argument("coins", nargs="+", help="例如 SOL DOGE SUI")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    try:
        if args.cmd == "scan":
            res = scan(cfg, args.exchange, args.top, quiet=args.quiet)
            print_table(res)
            if args.html:
                import screener_html  # noqa: PLC0415
                Path(args.html).write_text(screener_html.render(res, session_hint(cfg)), encoding="utf-8")
                print(f"HTML：{args.html}")
        else:
            res = scan(cfg, args.exchange, top=len(args.coins), symbols=args.coins, quiet=args.quiet)
            rows = res["requested"]
            print_now([r for r in rows if r.get("now")], cfg)
            for r in rows:
                if r["reject"]:
                    print(f"  ! {r['coin']} 沒通過篩選門檻：{'；'.join(r['reject'])}")
            found = {r["coin"] for r in rows}
            missing = [c for c in args.coins if base_key(c.upper().replace("USDT", "").split("-")[0]) not in found]
            if missing:
                print("  找不到這些合約：" + "、".join(missing))
    except SourceError as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 2
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON：{args.json}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
