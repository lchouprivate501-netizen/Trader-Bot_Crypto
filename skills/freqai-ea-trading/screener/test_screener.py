#!/usr/bin/env python3
"""日內篩選器的離線測試（不需要網路或套件）：指標、門檻、評分、掛單簿滑價、三家交易所的回應解析、
整個 scan 流程（假交易所）、即時盤勢分類、HTML、CLI。

    python3 skills/freqai-ea-trading/screener/test_screener.py
"""
from __future__ import annotations

import io
import json
import math
import random
import sys
import tempfile
import time
from datetime import datetime, timezone
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intraday_screener as sc  # noqa: E402
import screener_html  # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def make_bars(closes: list, start_ms: int, qv: float = 1e6, wick: float = 0.001) -> list:
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append([start_ms + i * sc.BAR_MS, o, max(o, c) * (1 + wick), min(o, c) * (1 - wick), c, qv])
        prev = c
    return out


def trend_path(n: int, p0: float = 100, step: float = 0.002, noise: float = 0.0, seed: int = 1) -> list:
    rnd = random.Random(seed)
    out, p = [], p0
    for _ in range(n):
        p *= 1 + step + rnd.gauss(0, noise)
        out.append(p)
    return out


def zigzag_path(n: int, p0: float = 100, amp: float = 0.01) -> list:
    return [p0 * (1 + (amp if i % 2 else -amp)) for i in range(n)]


def walk_path(n: int, p0: float = 100, vol: float = 0.004, seed: int = 7) -> list:
    rnd = random.Random(seed)
    out, p = [], p0
    for _ in range(n):
        p *= 1 + rnd.gauss(0, vol)
        out.append(p)
    return out


CFG = sc.load_config()
DAY0 = 1_760_000_000_000 // sc.DAY_MS * sc.DAY_MS


def test_chunk_stats() -> None:
    print("指標")
    up = sc.chunk_stats(make_bars(trend_path(96), DAY0), DAY0)
    zz = sc.chunk_stats(make_bars(zigzag_path(96), DAY0), DAY0)
    check("單邊上漲：整天 ER ≈ 1", up["er"] > 0.99, str(up["er"]))
    check("單邊上漲：6 個 4 小時區塊、每塊 ER ≈ 1", len(up["blocks"]) == 6 and min(b[0] for b in up["blocks"]) > 0.99)
    check("來回洗：4 小時 ER ≈ 0", max(b[0] for b in zz["blocks"]) < 0.1, str(zz["blocks"]))
    check("振幅 rng = (H-L)/O", abs(up["rng"] - (up["h"] - up["l"]) / up["o"] * 100) < 1e-3)
    check("區塊序號 0..5", [b[4] for b in up["blocks"]] == list(range(6)))
    check("少於 90 根就當缺資料", sc.chunk_stats(make_bars(trend_path(80), DAY0), DAY0) is None)
    check("成交額加總", up["qv"] == 96 * 1e6)
    # 變異數比：單邊 > 1、來回洗 < 1
    rw = sc.chunk_stats(make_bars(trend_path(96, step=0.001, noise=0.003), DAY0), DAY0)
    check("變異數比：趨勢 > 來回洗", rw["s16"] / rw["s1"] > zz["s16"] / zz["s1"])


def test_window() -> None:
    print("回看期指標")
    n = 14
    bars = make_bars(trend_path(n * 96, step=0.0005, noise=0.002), DAY0)
    days = sc.split_days(bars, DAY0 + n * sc.DAY_MS, n)
    check("split_days 切出 14 段", len(days) == n and all(days))
    m = sc.window_metrics(days, CFG)
    check("指標齊全", all(k in m for k in ("er4h", "chop_rate", "vr4h", "range_pct", "rvol", "qv_med")))
    check("RVOL：量不變時 = 1", abs(m["rvol"] - 1) < 1e-9)
    days2 = list(days)
    days2[3] = days2[5] = days2[7] = None
    check("缺 3 天就不算", sc.window_metrics(days2, CFG) is None)
    days3 = list(days)
    days3[-1] = None
    check("最近一天缺資料就不算", sc.window_metrics(days3, CFG) is None)
    zz = sc.window_metrics(sc.split_days(make_bars(zigzag_path(n * 96), DAY0), DAY0 + n * sc.DAY_MS, n), CFG)
    check("來回洗：盤整率 100%", zz["chop_rate"] == 1.0)
    check("趨勢：盤整率低於來回洗", m["chop_rate"] < zz["chop_rate"])
    check("週末/平日比有算（隨機資料 ≈ 1）", 0.5 < m["weekend_range_ratio"] < 2 and 0.5 < m["weekend_qv_ratio"] < 2,
          str((m.get("weekend_range_ratio"), m.get("weekend_qv_ratio"))))
    corr_self = sc.window_metrics(days, CFG, btc_days=days)["btc_corr"]
    check("和自己相關 = 1", abs(corr_self - 1) < 1e-9)


def test_gate_and_score() -> None:
    print("門檻與評分")
    base = {"days": 14, "qv_24h": 5e7, "qv_med": 5e7, "range_pct": 6.0, "er4h": 0.3, "chop_rate": 0.3,
            "vr4h": 1.0, "vr1h": 1.0, "rvol": 1.0, "er_day": 0.1, "body": 0.4, "er4h_3d": 0.3, "move4h_pct": 1.5,
            "tr15_pct": 0.5, "expansion": 1.0, "chg_24h_pct": 2.0}
    ok = {"base": "SOL", "coin": "SOL", "metrics": base, "age_days": 400}
    check("正常的幣合格", sc.gate(ok, CFG) == [])
    check("穩定幣剔除", sc.gate({**ok, "base": "USDC"}, CFG) != [])
    check("1000 倍代號也辨識（1000PEPE → PEPE）", sc.base_key("1000PEPE") == "PEPE" and sc.base_key("1MBABYDOGE") == "BABYDOGE")
    check("成交額不足剔除", any("中位數" in w for w in sc.gate({**ok, "metrics": {**base, "qv_med": 1e6}}, CFG)))
    check("振幅太小剔除", any("振幅" in w for w in sc.gate({**ok, "metrics": {**base, "range_pct": 1.0}}, CFG)))
    check("振幅過熱剔除", any("過熱" in w for w in sc.gate({**ok, "metrics": {**base, "range_pct": 40.0}}, CFG)))
    check("新上市剔除", any("上市" in w for w in sc.gate({**ok, "age_days": 3}, CFG)))
    check("指數合約剔除", any("不是加密貨幣" in w for w in sc.gate({**ok, "base": "BTCDOM"}, CFG)))
    check("交易所標示非加密（股票 / 商品）剔除", any("不是加密貨幣" in w for w in sc.gate({**ok, "non_crypto": True}, CFG)))
    check("清單上的股票 / 商品合約剔除（NVDA、XAU、HK0700）",
          all(any("不是加密貨幣" in w for w in sc.gate({**ok, "base": b}, CFG)) for b in ("NVDA", "XAU", "HK0700")))
    check("BTC、ETH 不在非加密清單", "BTC" not in sc.NON_CRYPTO and "ETH" not in sc.NON_CRYPTO)
    wk = {**base, "weekend_range_ratio": 0.5, "weekend_qv_ratio": 0.15}
    check("清單外的新合約：週末冷清 → 疑似股票剔除", any("週末" in w for w in sc.gate({**ok, "metrics": wk}, CFG)))
    check("週末成交額正常 → 不剔除", sc.gate({**ok, "metrics": {**wk, "weekend_qv_ratio": 0.8}}, CFG) == [])
    check("週末量少但振幅正常（加密貨幣常見）→ 不剔除",
          sc.gate({**ok, "metrics": {**wk, "weekend_range_ratio": 1.1}}, CFG) == [])
    check("價差太大剔除", any("價差" in w for w in sc.gate({**ok, "spread_bps": 20}, CFG)))
    check("滑價太大剔除", any("滑價" in w for w in sc.gate({**ok, "impact_bps": 30, "spread_bps": 1}, CFG)))
    check("掛單簿不夠深剔除", any("深度" in w for w in sc.gate({**ok, "book_checked": True, "spread_bps": 1}, CFG)))
    check("百分位（含同值）", sc.pct_ranks([3, 1, 2, 2]) == [1.0, 0.0, 0.5, 0.5])
    rows = [{"reject": [], "metrics": {**base, "er4h": e, "chop_rate": c}} for e, c in ((0.4, 0.1), (0.2, 0.5), (0.3, 0.3))]
    rows.append({"reject": ["x"], "metrics": base})
    sc.score_rows(rows, CFG)
    check("趨勢性高的分數較高", rows[0]["score"] > rows[2]["score"] > rows[1]["score"])
    check("不合格的不評分", "score" not in rows[3])


def test_book() -> None:
    print("掛單簿")
    bids = [(99.9, 100), (99.8, 100)]
    asks = [(100.1, 100), (100.2, 100)]
    b = sc._book_metrics(bids, asks, 5000)
    check("價差 bp", abs(b["spread_bps"] - 20.0) < 0.01, str(b))
    check("市價單滑價 bp（一檔吃完）", abs(b["impact_bps"] - 10.0) < 0.01, str(b))
    b2 = sc._book_metrics(bids, asks, 15000)
    check("吃到第二檔滑價變大", b2["impact_bps"] > b["impact_bps"])
    check("深度不夠 → None", sc._book_metrics(bids, asks, 1e6)["impact_bps"] is None)


class FakeHTTP:
    """依 URL 回傳固定的 JSON（格式照各交易所官方文件）。"""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append(url)
        for key, val in self.routes.items():
            if key in url:
                return val(url) if callable(val) else val
        return None


def test_adapters() -> None:
    print("交易所回應解析")
    now = int(time.time() * 1000)
    orig = sc.http_get
    try:
        sc.http_get = FakeHTTP({
            "/fapi/v1/exchangeInfo": {"symbols": [
                {"symbol": "SOLUSDT", "baseAsset": "SOL", "quoteAsset": "USDT", "contractType": "PERPETUAL",
                 "status": "TRADING", "onboardDate": now - 500 * sc.DAY_MS},
                {"symbol": "SOLUSDT_260327", "baseAsset": "SOL", "quoteAsset": "USDT", "contractType": "CURRENT_QUARTER",
                 "status": "TRADING"},
                {"symbol": "SOLUSDC", "baseAsset": "SOL", "quoteAsset": "USDC", "contractType": "PERPETUAL", "status": "TRADING"},
                {"symbol": "TSLAUSDT", "baseAsset": "TSLA", "quoteAsset": "USDT", "contractType": "PERPETUAL",
                 "status": "TRADING", "underlyingType": "EQUITY"}]},
            "/fapi/v1/ticker/24hr": [{"symbol": "SOLUSDT", "quoteVolume": "1234567890.5", "lastPrice": "150.1",
                                      "priceChangePercent": "-3.2"},
                                     {"symbol": "TSLAUSDT", "quoteVolume": "9e8", "lastPrice": "400",
                                      "priceChangePercent": "1"}],
            "/fapi/v1/premiumIndex": [{"symbol": "SOLUSDT", "lastFundingRate": "0.00010000"}],
            "/fapi/v1/klines": [[now - 2 * sc.BAR_MS, "1", "2", "0.5", "1.5", "10", now, "15.5", 3, "5", "7", "0"]],
            "/fapi/v1/depth": {"bids": [["99.9", "1000"]], "asks": [["100.1", "1000"]]},
        })
        u = sc.Binance().universe()
        check("Binance：只取 USDT 永續", [x["symbol"] for x in u] == ["SOLUSDT", "TSLAUSDT"])
        check("Binance：underlyingType 不是 COIN 的標成非加密", [x["non_crypto"] for x in u] == [False, True])
        check("Binance：成交額、資金費、上市天數", u[0]["qv_24h"] == 1234567890.5 and u[0]["funding"] == 1e-4
              and 499 < u[0]["age_days"] < 501)
        k = sc.Binance().klines("SOLUSDT", 10)
        check("Binance K 線：成交額取 quote volume", k[0][5] == 15.5 and k[0][4] == 1.5)
        check("Binance 掛單簿", sc.Binance().book("SOLUSDT", 1000)["spread_bps"] == 20.0)

        def bybit_kline(url):
            end = int(url.split("end=")[1]) if "end=" in url else now
            t0 = (end // sc.BAR_MS) * sc.BAR_MS
            return {"result": {"list": [[str(t0 - i * sc.BAR_MS), "1", "2", "0.5", "1.5", "10", "15"] for i in range(1000)]}}
        sc.http_get = FakeHTTP({
            "instruments-info": {"result": {"list": [
                {"symbol": "SUIUSDT", "baseCoin": "SUI", "quoteCoin": "USDT", "contractType": "LinearPerpetual",
                 "status": "Trading", "launchTime": str(now - 100 * sc.DAY_MS)},
                {"symbol": "SUIPERP", "baseCoin": "SUI", "quoteCoin": "USDC", "contractType": "LinearPerpetual",
                 "status": "Trading"}], "nextPageCursor": ""}},
            "tickers": {"result": {"list": [{"symbol": "SUIUSDT", "turnover24h": "500000000", "lastPrice": "3.2",
                                             "price24hPcnt": "0.051", "fundingRate": "-0.0002"}]}},
            "/v5/market/kline": bybit_kline,
            "orderbook": {"result": {"b": [["3.199", "100000"]], "a": [["3.201", "100000"]]}},
        })
        u = sc.Bybit().universe()
        check("Bybit：只取 USDT 線性永續", [x["symbol"] for x in u] == ["SUIUSDT"])
        check("Bybit：漲跌幅換成 %、資金費", abs(u[0]["chg_24h_pct"] - 5.1) < 1e-9 and u[0]["funding"] == -0.0002)
        k = sc.Bybit().klines("SUIUSDT", 1500)
        ts = [x[0] for x in k]
        check("Bybit K 線：分頁補到 1500 根、舊→新、不重複", len(k) == 1500 and ts == sorted(set(ts)))
        check("Bybit 掛單簿", sc.Bybit().book("SUIUSDT", 1000)["impact_bps"] is not None)

        def okx_candles(url):
            after = int(url.split("after=")[1]) if "after=" in url else now
            n = 300 if "after=" not in url else 100
            t0 = (after // sc.BAR_MS) * sc.BAR_MS - (0 if "after=" not in url else sc.BAR_MS)
            rows = [[str(t0 - i * sc.BAR_MS), "1", "2", "0.5", "1.5", "10", "10", "15", "1"] for i in range(n)]
            if "after=" not in url:
                rows[0][8] = "0"  # 最新一根還沒收盤
            return {"data": rows}
        sc.http_get = FakeHTTP({
            "public/instruments": {"data": [
                {"instId": "DOGE-USDT-SWAP", "settleCcy": "USDT", "state": "live", "ctType": "linear", "ctVal": "1000",
                 "listTime": str(now - 900 * sc.DAY_MS)},
                {"instId": "DOGE-USD-SWAP", "settleCcy": "DOGE", "state": "live", "ctType": "inverse", "ctVal": "10"}]},
            "market/tickers": {"data": [{"instId": "DOGE-USDT-SWAP", "last": "0.2", "open24h": "0.19",
                                         "volCcy24h": "5000000000"}]},
            "candles": okx_candles,
            "market/books": {"data": [{"bids": [["0.1999", "500", "0", "3"]], "asks": [["0.2001", "500", "0", "3"]]}]},
        })
        okx = sc.OKX()
        u = okx.universe()
        check("OKX：只取 USDT 線性永續", [x["symbol"] for x in u] == ["DOGE-USDT-SWAP"])
        check("OKX：成交額 = 幣數量 × 價格", u[0]["qv_24h"] == 5e9 * 0.2)
        sc.time.sleep, real_sleep = (lambda s: None), sc.time.sleep
        try:
            k = okx.klines("DOGE-USDT-SWAP", 1000)
        finally:
            sc.time.sleep = real_sleep
        ts = [x[0] for x in k]
        check("OKX K 線：分頁、略過未收盤、成交額取 volCcyQuote", len(k) == 1000 and ts == sorted(set(ts)) and k[-1][5] == 15.0)
        b = okx.book("DOGE-USDT-SWAP", 50000)
        check("OKX 掛單簿：張數 × ctVal", b["impact_bps"] is not None and abs(b["spread_bps"] - 10.0) < 0.01, str(b))
    finally:
        sc.http_get = orig


class FakeExchange:
    """假交易所：四個趨勢幣、四個來回洗的幣、一個穩定幣、一個成交額太小的幣。"""
    name = "fake"

    def __init__(self):
        now = int(time.time() * 1000)
        self.end = now // sc.BAR_MS * sc.BAR_MS
        n = 14 * 96 + 8
        start = self.end - n * sc.BAR_MS
        self.data = {}
        spec = {
            "BTC": (walk_path(n, 60000, 0.003, 1), 5e9 / 96),
            "TRND1": (trend_path(n, 10, 0.0008, 0.003, 2), 2e8 / 96),
            "TRND2": (trend_path(n, 5, -0.0008, 0.003, 3), 1.5e8 / 96),
            "TRND3": (trend_path(n, 3, 0.0007, 0.0035, 4), 1e8 / 96),
            "TRND4": (trend_path(n, 2, -0.0007, 0.0035, 5), 1e8 / 96),
            "CHOP1": ([10 * (1 + 0.006 * math.sin(i / 2) + random.Random(i).gauss(0, 0.004)) for i in range(n)], 3e8 / 96),
            "CHOP2": (zigzag_path(n, 5, 0.008), 2e8 / 96),
            "CHOP3": ([3 * (1 + 0.007 * math.sin(i / 3) + random.Random(i + 9).gauss(0, 0.004)) for i in range(n)], 1e8 / 96),
            "CHOP4": (zigzag_path(n, 2, 0.009), 1e8 / 96),
            "USDC": ([1.0 + 0.0001 * (i % 2) for i in range(n)], 1e9 / 96),
            "TINY": (trend_path(n, 1, 0.001, 0.004, 6), 1e5 / 96),
        }
        for coin, (path, qv) in spec.items():
            self.data[coin + "USDT"] = make_bars(path, start, qv)

    def universe(self):
        return [{"exchange": self.name, "symbol": s, "base": s[:-4], "qv_24h": sum(b[5] for b in bars[-96:]),
                 "last": bars[-1][4], "chg_24h_pct": 0.0, "funding": 0.0008 if s == "TRND1USDT" else 0.0001,
                 "age_days": 300} for s, bars in self.data.items()]

    def klines(self, symbol, n):
        return self.data[symbol][-n:]

    def book(self, symbol, notional):
        return {"spread_bps": 1.0, "impact_bps": 2.0, "book_checked": True}


def test_scan() -> None:
    print("整個 scan 流程（假交易所）")
    sc.SOURCES["fake"] = FakeExchange
    cfg = dict(CFG, min_range_pct=0.5, min_median_qv_usdt=1e7, min_qv_24h_usdt=1e7)
    res = sc.scan(cfg, "fake", top=6, quiet=True)
    wl = [r["coin"] for r in res["watchlist"]]
    rej = {x["coin"]: x["why"] for x in res["rejected"]}
    listed = wl + [r["coin"] for r in res["bench"]]
    check("穩定幣、成交額太小的不會進清單", "USDC" not in listed and "TINY" not in listed, str(listed))
    trend = [i for i, c in enumerate(listed) if c.startswith("TRND")]
    chop = [i for i, c in enumerate(listed) if c.startswith("CHOP")]
    check("四個趨勢幣都排在來回洗的幣前面", len(trend) == 4 and max(trend) < min(chop), str(listed))
    check("第一名是趨勢幣", wl[0].startswith("TRND"), str(wl))
    check("觀察清單附即時盤勢", all("now" in r for r in res["watchlist"]))
    t1 = next(r for r in res["watchlist"] if r["coin"] == "TRND1")
    check("資金費擁擠會提醒", any("資金費" in w for w in t1["warnings"]))
    check("和 BTC 的相關性有算", "btc_corr" in t1["metrics"])
    chop = next(r for r in res["watchlist"] + res["bench"] if r["coin"] == "CHOP2")
    check("來回洗的幣 now = 盤整", chop.get("now", {}).get("state") in (None, "CHOP"), str(chop.get("now")))
    page = screener_html.render(res)
    check("HTML 有清單、沒有外部資源（無外部 script / css）", "TRND1" in page and "<script src" not in page
          and "<link" not in page and "http" not in page.split("<body>")[1].split("<script")[0])
    json.dumps(res, ensure_ascii=False)
    check("結果可存成 JSON", True)

    out = io.StringIO()
    with tempfile.TemporaryDirectory() as td, redirect_stdout(out), redirect_stderr(io.StringIO()):
        cfgp = Path(td) / "c.json"
        cfgp.write_text(json.dumps({"min_range_pct": 0.5, "min_median_qv_usdt": 1e7, "min_qv_24h_usdt": 1e7}))
        sc_choices = sc.main.__code__  # noqa: F841
        orig_parse = sc.argparse.ArgumentParser.parse_args
        rc = _run_cli(["scan", "--exchange", "binance", "--config", str(cfgp), "--quiet",
                       "--json", str(Path(td) / "o.json"), "--html", str(Path(td) / "o.html")])
        sc.argparse.ArgumentParser.parse_args = orig_parse
        ok_files = (Path(td) / "o.json").exists() and (Path(td) / "o.html").exists()
        rc2 = _run_cli(["now", "TRND1", "CHOP2", "--exchange", "binance", "--config", str(cfgp), "--quiet"])
    text = out.getvalue()
    check("CLI scan：表格、JSON、HTML", rc == 0 and ok_files and "TRND1" in text, text[-500:])
    check("CLI now：列出指定幣的盤勢", rc2 == 0 and "來回洗" in text.split("JSON：")[-1], text[-400:])
    check("CLI 說明近 4h 不是預測、附時段盤整率", ("不能預測" in text or "無法預測" in text) and "UTC" in text)

    sc.SOURCES["binance"] = sc.Binance
    err = io.StringIO()
    orig = sc.http_get

    def boom(url, **kw):
        raise sc.SourceError("連不到 fapi.binance.com（HTTP 451）")
    sc.http_get = boom
    with redirect_stderr(err), redirect_stdout(io.StringIO()):
        rc3 = sc.main(["scan", "--quiet"])
    sc.http_get = orig
    check("連不到交易所：結束碼 2 並說明", rc3 == 2 and "451" in err.getvalue(), err.getvalue())


def _run_cli(argv):
    saved = sc.SOURCES["binance"]
    sc.SOURCES["binance"] = FakeExchange
    try:
        return sc.main(argv)
    finally:
        sc.SOURCES["binance"] = saved


def test_state() -> None:
    print("即時盤勢分類")
    n = 14 * 96
    days = sc.split_days(make_bars(walk_path(n), DAY0), DAY0 + 14 * sc.DAY_MS, 14)
    zz = make_bars(zigzag_path(40, amp=0.004), DAY0)
    check("來回洗 → CHOP", sc.intraday_state(zz, days, CFG)["state"] == "CHOP")
    up = make_bars(trend_path(40, step=0.004), DAY0)
    check("單邊放量上漲 → TREND_UP", sc.intraday_state(up, days, CFG)["state"] == "TREND_UP")
    dn = make_bars(trend_path(40, step=-0.004), DAY0)
    check("單邊下跌 → TREND_DOWN", sc.intraday_state(dn, days, CFG)["state"] == "TREND_DOWN")
    h = sc.session_hint(CFG, at_ms=DAY0 + 13 * sc.HOUR_MS)
    check("時段提醒：UTC 13 點 → 12-16 時段（台北 20-24）", "UTC 12-16（台北 20-24）" in h, h)
    flat = make_bars(trend_path(40, step=0.00005, noise=0.00002), DAY0, wick=0.00001)
    s = sc.intraday_state(flat, days, CFG)["state"]
    check("振幅極小但有方向 → SQUEEZE", s == "SQUEEZE", s)


# ----------------------------------------------------------------------------------------------
# 新聞催化劑
# ----------------------------------------------------------------------------------------------

import news_catalyst as nc  # noqa: E402

NOW = 1_763_300_000_000  # 固定的「現在」（毫秒）


def _rfc822(ms):
    import email.utils as eu
    return eu.format_datetime(datetime.fromtimestamp(ms / 1000, timezone.utc))


RSS = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>X</title>
<item><title>Bybit Will List SUI Perpetual &amp; Spot</title><link>https://ex.com/a</link>
<pubDate>{_rfc822(NOW - 2 * 3600_000)}</pubDate><description><![CDATA[<p>New <b>listing</b> for $SUI.</p>]]></description></item>
<item><title>Fed holds rates steady; Powell signals patience</title><link>https://ex.com/b</link>
<pubDate>{_rfc822(NOW - 5 * 3600_000)}</pubDate></item>
<item><title>Ancient news about DOGE</title><link>https://ex.com/c</link><pubDate>{_rfc822(NOW - 80 * 3600_000)}</pubDate></item>
</channel></rss>""".encode()

ATOM = f"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Exploit drains $12M from protocol, TAO bridge paused</title><link href="https://ex.com/d"/>
<updated>{datetime.fromtimestamp((NOW - 3600_000) / 1000, timezone.utc).isoformat().replace("+00:00", "Z")}</updated>
<summary>Attackers compromised the bridge.</summary></entry></feed>""".encode()


def test_news_parsing() -> None:
    print("新聞：解析")
    items = nc.parse_feed(RSS, "coindesk")
    check("RSS：三則、標題去 HTML 實體", len(items) == 3 and items[0]["title"] == "Bybit Will List SUI Perpetual & Spot")
    check("RSS：pubDate 轉毫秒", abs(items[0]["ts"] - (NOW - 2 * 3600_000)) < 1000)
    check("RSS：description 去掉 HTML 標籤", items[0]["summary"] == "New listing for $SUI.", items[0]["summary"])
    a = nc.parse_feed(ATOM, "theblock")
    check("Atom：link href、updated", len(a) == 1 and a[0]["url"] == "https://ex.com/d" and abs(a[0]["ts"] - (NOW - 3600_000)) < 1000)
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    try:
        nc.parse_feed(bomb, "x")
        check("含 ENTITY 的 XML 拒絕解析", False)
    except ValueError:
        check("含 ENTITY 的 XML 拒絕解析", True)
    by = nc.parse_bybit({"retCode": 0, "result": {"total": 2, "list": [
        {"title": "New Listing: XYZUSDT Perpetual Contract", "description": "", "type": {"title": "New Listings", "key": "new_crypto"},
         "tags": ["Derivatives"], "url": "https://announcements.bybit.com/x", "dateTimestamp": NOW - 3600_000},
        {"title": "Delisting of ABCUSDT Perpetual Contract", "description": "", "type": {"title": "Delistings", "key": "delistings"},
         "tags": [], "url": "https://announcements.bybit.com/y", "dateTimestamp": NOW - 7200_000}]}})
    check("Bybit 公告：type.key → 上線 / 下架", [x["hint_type"] for x in by] == ["listing", "delisting"])
    ok1 = nc.parse_okx({"code": "0", "data": [{"details": [{"annType": "announcements-delistings", "pTime": str(NOW),
                                                             "title": "OKX to delist ABC", "url": "https://okx.com/z"}], "totalPage": "1"}]})
    ok2 = nc.parse_okx({"code": "0", "data": [{"annType": "announcements-new-listings", "pTime": str(NOW), "title": "OKX lists XYZ",
                                               "url": "https://okx.com/w"}]})
    check("OKX 公告：兩種回應形狀都能解析", ok1[0]["hint_type"] == "delisting" and ok2[0]["hint_type"] == "listing")
    cp = nc.parse_cryptopanic({"results": [{"title": "SOL rallies", "published_at": "2026-11-16T10:00:00Z",
                                            "url": "https://cp/1", "currencies": [{"code": "SOL"}]}]})
    check("CryptoPanic：幣別標記", cp[0]["coins_hint"] == ["SOL"])


def test_news_matching() -> None:
    print("新聞：對應到幣、分類")
    m = nc.Matcher(["BTC", "BCH", "SOL", "SUI", "1000PEPE", "DOGE", "TRUMP", "TAO", "SEC"], nc.load_aliases(CFG),
                   CFG["news"]["ambiguous_tickers"])
    check("$SOL、(SUI)、PEPEUSDT", m.match("$SOL and (SUI) pump; 1000PEPEUSDT perp") == {"SOL", "SUI", "PEPE"})
    check("Bitcoin Cash 不會被當成 BTC", m.match("Bitcoin Cash hard fork scheduled") == {"BCH"})
    check("名稱別名：Solana、Dogecoin", m.match("Solana and Dogecoin lead gains") == {"SOL", "DOGE"})
    check("SEC 是常見縮寫，不算代號", m.match("SEC sues exchange over staking") == set())
    check("模糊代號 TRUMP 要有 $ 才算", m.match("TRUMP says crypto") == set() and m.match("$TRUMP memecoin unlock") == {"TRUMP"})
    check("大寫代號整字：TAO", m.match("TAO jumps 12% after upgrade") == {"TAO"})
    cl = lambda t: nc.classify({"title": t, "summary": ""})[0]  # noqa: E731
    check("下架優先於上線（delist 含 list）", cl("Binance will delist XYZ and list ABC") == "delisting")
    check("駭客", cl("Exploit drains $12M from lending protocol") == "hack")
    check("總經", cl("Fed holds rates steady; Powell signals patience") == "macro")
    check("ETF", cl("Spot SOL ETF approved by regulators") == "etf")
    check("解鎖", cl("TIA faces $90M token unlock next week") == "unlock")
    check("公告類型提示優先", nc.classify({"title": "Notice", "summary": "", "hint_type": "delisting"})[0] == "delisting")


def _items():
    def it(src, tier, title, h, **kw):
        return {"source": src, "tier": tier, "title": title, "summary": "", "url": f"https://ex.com/{abs(hash(title)) % 999}",
                "ts": NOW - h * 3600_000, **kw}
    return [
        it("coindesk", "media", "Bybit Will List SUI Perpetual", 2),
        it("theblock", "media", "SUI listing draws record volume", 6),
        it("bybit", "official", "Delisting of DOGEUSDT Perpetual Contract", 3, hint_type="delisting"),
        it("decrypt", "media", "Exploit drains $12M as TAO bridge paused", 1),
        it("cointelegraph", "media", "SOL update: mainnet upgrade goes live", 30),
        it("coindesk", "media", "Fed holds rates steady; Powell signals patience", 5),
        it("coindesk", "media", "Market wrap: BTC, ETH, SOL, SUI, DOGE, TAO all slide", 1),
        it("coindesk", "media", "Old SOL story", 60),
    ]


def test_news_annotate() -> None:
    print("新聞：打分與標記")
    per, macro = nc.annotate(_items(), ["SUI", "DOGE", "TAO", "SOL", "BTC", "ETH"], CFG, now_ms=NOW)
    check("新鮮上線新聞 → 焦點", per["SUI"]["tag"] == "FOCUS" and per["SUI"]["n_fresh"] == 2, str(per.get("SUI")))
    check("官方下架公告 → 避開、delisting", per["DOGE"]["tag"] == "AVOID" and per["DOGE"]["delisting"])
    check("駭客 → 避開（不算下架）", per["TAO"]["tag"] == "AVOID" and per["TAO"]["hack"] and not per["TAO"]["delisting"])
    check("超過 24 小時的新聞 → 舊聞；超過 48 小時不算", per["SOL"]["tag"] == "OLD" and per["SOL"]["n"] == 1)
    check("一次提到一堆幣的行情回顧不算個別催化劑", "BTC" not in per and "ETH" not in per)
    check("沒有對應幣的總經新聞放在 macro", len(macro) == 1 and "Powell" in macro[0]["title"])
    w_new = [r["weight"] for r in per["SUI"]["top"]]
    check("時間衰減：越新的權重越高", w_new == sorted(w_new, reverse=True) and w_new[0] > w_new[1])
    media2 = [{"source": s, "tier": "media", "title": f"{s}: exchange to delist XYZ", "summary": "", "url": "", "ts": NOW - 3600_000}
              for s in ("coindesk", "theblock")]
    p2, _ = nc.annotate(media2, ["XYZ"], CFG, now_ms=NOW)
    check("兩家媒體都報導下架 → 也算下架", p2["XYZ"]["delisting"])
    p3, _ = nc.annotate(media2[:1], ["XYZ"], CFG, now_ms=NOW)
    check("只有一家媒體報導下架 → 避開但不算下架", p3["XYZ"]["tag"] == "AVOID" and not p3["XYZ"]["delisting"])


def test_news_fetch() -> None:
    print("新聞：抓取（模擬）")
    import os
    orig = sc.http_get

    def fake(url, **kw):
        if "coindesk" in url:
            return RSS
        if "theblock" in url:
            return ATOM
        if "bybit" in url:
            return {"result": {"list": [{"title": "Bybit Will List SUI Perpetual & Spot", "type": {"key": "new_crypto"},
                                         "url": "https://b/1", "dateTimestamp": NOW}]}}
        if "cryptopanic" in url:
            raise sc.SourceError(f"連不到 cryptopanic.com（HTTP 403）{url}")
        raise sc.SourceError("連不到（HTTP 403）")
    sc.http_get = fake
    os.environ["CRYPTOPANIC_TOKEN"] = "secret123"
    try:
        items, errors, ok = nc.fetch_all(CFG)
    finally:
        sc.http_get = orig
        os.environ.pop("CRYPTOPANIC_TOKEN", None)
    check("個別來源失敗不影響其他來源", set(ok) == {"coindesk", "theblock", "bybit"} and "okx" in errors)
    check("同標題多來源只留一次，保留官方來源",
          sum(1 for i in items if "Will List SUI" in i["title"]) == 1
          and next(i for i in items if "Will List SUI" in i["title"])["tier"] == "official")
    check("有 CRYPTOPANIC_TOKEN 才會用，錯誤訊息不洩漏金鑰",
          "cryptopanic" in errors and "secret123" not in errors["cryptopanic"], errors.get("cryptopanic", ""))


def test_news_scan() -> None:
    print("新聞：整合進 scan")
    sc.SOURCES["fake"] = FakeExchange
    cfg = dict(CFG, min_range_pct=0.5, min_median_qv_usdt=1e7, min_qv_24h_usdt=1e7)
    base = sc.scan(cfg, "fake", top=6, quiet=True)
    orig = nc.fetch_all
    news_items = [
        {"source": "bybit", "tier": "official", "title": "Delisting of CHOP1USDT Perpetual Contract", "summary": "",
         "url": "https://b/1", "ts": time.time() * 1000 - 3600_000, "hint_type": "delisting"},
        {"source": "coindesk", "tier": "media", "title": "TRND3 lists on major exchange; $TRND3 perpetual launches",
         "summary": "", "url": "javascript:alert(1)", "ts": time.time() * 1000 - 7200_000},
        {"source": "coindesk", "tier": "media", "title": "Fed cuts rates by 25bp", "summary": "", "url": "https://c/2",
         "ts": time.time() * 1000 - 3600_000},
    ]
    nc.fetch_all = lambda cfg, workers=6: (news_items, {"okx": "HTTP 403"}, ["bybit", "coindesk"])
    try:
        res = sc.scan(cfg, "fake", top=6, quiet=True, news=True)
    finally:
        nc.fetch_all = orig
    rej = {x["coin"]: x["why"] for x in res["rejected"]}
    check("交易所公告下架 → 剔除", any("下架" in w for w in rej.get("CHOP1", [])), str(rej.get("CHOP1")))
    check("焦點清單", [r["coin"] for r in res["focus"]] == ["TRND3"], str([r["coin"] for r in res["focus"]]))
    check("避開清單含下架的幣", [a["coin"] for a in res["avoid"]] == ["CHOP1"])
    t3 = next(r for r in res["watchlist"] + res["bench"] if r["coin"] == "TRND3")
    check("催化劑分數寫進 metrics", t3["metrics"]["catalyst_score"] > 0)
    s0 = {r["coin"]: r["score"] for r in base["watchlist"] + base["bench"] if r["coin"] != "CHOP1"}
    s1 = {r["coin"]: r["score"] for r in res["watchlist"] + res["bench"]}
    order0 = [c for c in sorted(s0, key=lambda c: -s0[c])]
    order1 = [c for c in sorted(s1, key=lambda c: -s1[c])]
    check("權重 0：新聞不改變其他幣的相對排名", order0 == order1, f"{order0} vs {order1}")
    check("總經新聞", res["news"]["macro"] and "Fed" in res["news"]["macro"][0]["title"])
    page = screener_html.render(res)
    check("HTML：新聞區塊、javascript: 連結不會變成超連結", "新聞催化劑" in page and "javascript:alert" not in page.replace(
        "javascript:alert(1)", "") and "href='javascript" not in page)
    out = io.StringIO()
    with redirect_stdout(out):
        sc.print_table(res)
    text = out.getvalue()
    check("文字輸出：焦點、避開、總經、來源狀態", all(k in text for k in ("今日焦點", "避開 CHOP1", "總經", "失敗 okx")), text[-600:])
    with tempfile.TemporaryDirectory() as td:
        path = sc.write_log(res, td)
        check("--log 存到 <日期>/scan-HHMMZ.json", Path(path).parent.name == res["data_until_utc"][:10]
              and Path(path).name.startswith("scan-") and json.loads(Path(path).read_text())["focus"])


def test_forward() -> None:
    print("前向驗證（模擬歷史資料庫）")
    import research
    t0 = 1_763_164_800_000  # 2025-11-15 00:00 UTC
    day0 = research.ymd(t0)
    res = {"data_until_utc": f"{day0} 00:00", "watchlist": [], "bench": []}
    for i in range(12):
        coin = f"C{i}"
        res["watchlist"].append({"coin": coin, "exchange": "binance", "symbol": coin + "USDT", "score": 100 - i,
                                 **({"news": {"tag": "FOCUS", "n_fresh": 1}} if i < 3 else {})})
    paths = {f"C{i}USDT": (trend_path(96, 10, 0.002, 0.001, i) if i < 3 else zigzag_path(96, 10, 0.004)) for i in range(12)}
    orig = research._archive_bars
    research._archive_bars = lambda sym, day: make_bars(paths[sym], t0) if day == day0 and sym in paths else []
    try:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / day0
            d.mkdir()
            (d / "scan-0000Z.json").write_text(json.dumps(res))
            (d / "ai_report.json").write_text(json.dumps({"focus": ["C1"], "avoid": ["C5"]}))
            with redirect_stdout(io.StringIO()):
                out = research.cmd_forward(type("A", (), {"log": td})(), CFG)
    finally:
        research._archive_bars = orig
    g = out["groups"]
    check("前向：量測 1 天", out["evaluated_days"] == 1, str(out))
    check("前向：焦點組（趨勢）盤整少於全部合格", g["程式標記：焦點"]["chop"] < g["全部合格"]["chop"])
    check("前向：AI 焦點 / 避開分組", g["AI：焦點"]["days"] == 1 and g["AI：避開"]["chop"] == 1.0)
    check("前向：樣本不足時不判定", "樣本不足" in out["verdicts"]["程式標記：焦點"])


def test_prompts() -> None:
    print("排程提示詞")
    import re as _re
    pdir = Path(__file__).resolve().parent / "prompts"
    repo = Path(__file__).resolve().parents[3]
    names = ["daily_watchlist.md", "pre_session.md", "weekly_review.md"]
    for n in names:
        text = (pdir / n).read_text(encoding="utf-8")
        check(f"{n}：有版本號", text.startswith("<!-- prompt_version:"))
        paths = set(_re.findall(r"skills/freqai-ea-trading/[\w./-]+\.(?:py|md|json|sh)", text))
        missing = [p for p in paths if not (repo / p).exists()]
        check(f"{n}：提到的檔案都存在（{len(paths)} 個）", not missing, str(missing))
        check(f"{n}：有界線與自我檢查", "界線" in text and "自我檢查" in text)
    daily = (pdir / "daily_watchlist.md").read_text(encoding="utf-8")
    check("每日提示詞：用 --news --log、說明新聞未驗證", "--news --log" in daily and "尚未驗證" in daily)
    check("盤前提示詞：禁止 --log 與因近4h升級", "不要用 `--log`" in (pdir / "pre_session.md").read_text(encoding="utf-8"))
    schema = json.loads((pdir / "ai_report.schema.json").read_text(encoding="utf-8"))
    ex = json.loads((pdir / "ai_report.example.json").read_text(encoding="utf-8"))
    check("範例含 schema 的必要欄位", all(k in ex for k in schema["required"]))
    tiers = schema["properties"]["coins"]["items"]["properties"]["tier"]["enum"]
    types = schema["properties"]["coins"]["items"]["properties"]["catalysts"]["items"]["properties"]["type"]["enum"]
    check("範例的分級與催化劑類型都在 enum 內", all(c["tier"] in tiers for c in ex["coins"])
          and all(k["type"] in types for c in ex["coins"] for k in c["catalysts"]))
    check("schema 的催化劑類型 = 程式分類 + general", set(types) == {k for k, *_ in nc.TAXONOMY} | {"general"})
    check("範例的 focus / avoid 是大寫代號", all(_re.fullmatch(r"[A-Z0-9]+", c) for c in ex["focus"] + ex["avoid"]))
    readme = (pdir / "README.md").read_text(encoding="utf-8")
    check("README 列出所有提示詞", all(n in readme for n in names + ["ai_report.schema.json", "persist_runs.sh"]))


if __name__ == "__main__":
    test_chunk_stats()
    test_window()
    test_gate_and_score()
    test_book()
    test_adapters()
    test_scan()
    test_state()
    test_news_parsing()
    test_news_matching()
    test_news_annotate()
    test_news_fetch()
    test_news_scan()
    test_forward()
    test_prompts()
    print(f"\n{PASS} 通過，{FAIL} 失敗")
    sys.exit(1 if FAIL else 0)
