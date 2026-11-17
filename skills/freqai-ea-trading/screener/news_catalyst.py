#!/usr/bin/env python3
"""新聞催化劑：抓公開新聞與交易所公告 → 對應到幣 → 分類 → 依時間衰減打分。只用標準函式庫、不需金鑰。

來源（screener/config.json 的 news.feeds 可增減）：
  bybit        Bybit 官方公告 API（GET /v5/announcements/index，文件公開；上幣、下架、合約調整）
  okx          OKX 官方公告 API（GET /api/v5/support/announcements；回應格式未能連線核對，解析採寬鬆寫法）
  rss          CoinDesk、The Block、Cointelegraph、Decrypt 等 RSS / Atom
  cryptopanic  有設定環境變數 CRYPTOPANIC_TOKEN 才會用（金鑰放環境變數，不要貼進對話或檔案）
Binance 的公告清單沒有正式公開 API（官方論壇不建議用內部 bapi），所以不抓；Binance 的上幣 / 下架通常也會出現在媒體 RSS。

狀態：**未驗證**。歷史新聞無法在這個環境取得，所以催化劑在分數裡的權重預設為 0，只用來標記「焦點 / 避開」與
硬性剔除「交易所公告下架」的合約；scan --log 會把每次結果存下來，累積後用 research.py forward 檢驗。

單獨使用：
  python3 news_catalyst.py SOL DOGE SUI          # 這幾個幣最近 48 小時的催化劑
  python3 news_catalyst.py --macro               # 只看總經 / 全市場新聞
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import intraday_screener as sc  # noqa: E402

HOUR_MS = 3600 * 1000
MAX_FEED_BYTES = 3_000_000

# 類型：(鍵, 中文, 方向 pos/neg/unc, 影響 1-3, 樣式)。依序比對，第一個符合的就是類型（下架、駭客優先於上線）。
TAXONOMY = [
    ("delisting", "下架", "neg", 3, [r"\bdelist", r"will (?:remove|cease trading|terminate)", r"下架", r"終止交易"]),
    ("hack", "駭客 / 漏洞", "neg", 3, [r"\bhack", r"\bexploit", r"\bdrain(?:ed|s)?\b", r"\bbreach", r"\bstolen\b",
                                     r"\bcompromised\b", r"被盜", r"攻擊"]),
    ("listing", "上線", "pos", 2, [r"\bwill list\b", r"\blisting\b", r"\blists\b", r"\blisted on\b", r"perpetual",
                                  r"上線", r"上幣", r"上市"]),
    ("etf", "ETF", "pos", 2, [r"\betfs?\b"]),
    ("regulation", "監管 / 訴訟", "unc", 2, [r"\bsec\b", r"lawsuit", r"\bsues?\b", r"\bsued\b", r"\bcharge[sd]?\b",
                                         r"regulat", r"\bbans?\b", r"\bsettle", r"\bcourt\b", r"\bcftc\b", r"\bdoj\b",
                                         r"監管", r"訴訟"]),
    ("unlock", "代幣解鎖", "neg", 2, [r"\bunlock", r"\bvesting\b", r"解鎖"]),
    ("upgrade", "升級 / 主網", "pos", 1, [r"\bmainnet\b", r"\bupgrade", r"hard ?fork", r"\btestnet\b", r"升級", r"主網"]),
    ("partnership", "合作 / 採用", "pos", 1, [r"\bpartner", r"\bintegrat", r"\badopt", r"\btreasury\b", r"\bacquir",
                                           r"合作"]),
    ("tokenomics", "空投 / 銷毀 / 回購", "pos", 1, [r"\bairdrop", r"\bburn", r"\bbuyback", r"空投", r"銷毀", r"回購"]),
    ("flows", "資金流 / 爆倉", "unc", 1, [r"\binflows?\b", r"\boutflows?\b", r"\bwhales?\b", r"\bliquidat"]),
    ("exchange_ops", "交易所調整", "unc", 1, [r"maintenance", r"\bsuspen", r"\bleverage\b", r"funding rate", r"\bmargin\b",
                                          r"維護", r"暫停"]),
    ("macro", "總經", "unc", 2, [r"\bcpi\b", r"\bfomc\b", r"\bthe fed\b", r"\bfed(?:eral reserve)?\b", r"\bpowell\b",
                               r"rate (?:cut|hike)", r"interest rates?", r"jobs report", r"\bnonfarm\b", r"\bpayrolls\b",
                               r"\btariffs?\b", r"\binflation\b", r"\bpce\b", r"\bgdp\b"]),
]
TYPE_ZH = {k: zh for k, zh, *_ in TAXONOMY} | {"general": "一般新聞"}
BYBIT_TYPE = {"new_crypto": "listing", "delistings": "delisting", "maintenance_updates": "exchange_ops"}

# 大寫英文縮寫裡常見、但不是幣的字（避免把 SEC、ETF、CEO 當成代號）
STOPWORDS = {
    "THE", "AND", "FOR", "NEW", "ALL", "ONE", "TOP", "BIG", "KEY", "LOW", "HIGH", "NOW", "OPEN", "REAL", "SAFE", "MOVE",
    "SEC", "ETF", "ETFS", "CEO", "CFO", "CTO", "USD", "USA", "FED", "CPI", "PCE", "GDP", "IPO", "API", "NFT", "NFTS",
    "DAO", "DEX", "CEX", "TVL", "ATH", "ATL", "OTC", "KYC", "AML", "FUD", "FOMO", "FOMC", "CFTC", "DOJ", "IRS", "EU",
    "UK", "US", "AI", "GPU", "CPU", "WEB", "WEB3", "DEFI", "CEFI", "RWA", "LST", "LRT", "BTCFI", "PEOPLE", "BANK",
    "SUN", "GAS", "ME", "IT", "IN", "ON", "AT", "BY", "TO", "OF", "OR", "AN", "A", "S", "T", "Q", "V", "X", "U", "B",
    "VS", "PR", "TV", "LIVE", "NEWS", "WHY", "HOW", "WHAT", "UPDATE", "JUST", "MORE", "BOOK",
}

_TAG = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text or ""))).strip()


# ----------------------------------------------------------------------------------------------
# 抓取與解析
# ----------------------------------------------------------------------------------------------

def _ts_from_any(s: str | None) -> int | None:
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        v = int(s)
        return v if v > 10**12 else v * 1000
    try:
        return int(email.utils.parsedate_to_datetime(s).timestamp() * 1000)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def parse_feed(raw: bytes, source: str) -> list[dict]:
    """RSS 2.0 或 Atom → [{source, title, summary, url, ts}]。拒絕含 DTD/實體宣告的 XML（防 XML 炸彈）。"""
    if len(raw) > MAX_FEED_BYTES:
        raw = raw[:MAX_FEED_BYTES]
    text = raw.decode("utf-8", errors="replace")
    if re.search(r"<!DOCTYPE|<!ENTITY", text[:5000], re.I):
        raise ValueError("feed 含 DTD / ENTITY 宣告，不解析")
    root = ET.fromstring(text)
    out = []

    def local(tag):
        return tag.rsplit("}", 1)[-1]

    for el in root.iter():
        name = local(el.tag)
        if name not in ("item", "entry"):
            continue
        f = {}
        for ch in el:
            n = local(ch.tag)
            if n == "link":
                f["link"] = ch.get("href") or (ch.text or "")
            elif n in ("title", "description", "summary", "pubDate", "published", "updated", "date"):
                f.setdefault(n, "".join(ch.itertext()))
        ts = _ts_from_any(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date"))
        title = clean(f.get("title", ""))
        if title and ts:
            out.append({"source": source, "title": title, "summary": clean(f.get("description") or f.get("summary", ""))[:600],
                        "url": (f.get("link") or "").strip(), "ts": ts})
    return out


def parse_bybit(data: dict) -> list[dict]:
    out = []
    for it in ((data or {}).get("result") or {}).get("list") or []:
        ts = it.get("dateTimestamp") or it.get("publishTime") or it.get("startDateTimestamp")
        key = ((it.get("type") or {}).get("key") or "")
        out.append({"source": "bybit", "title": clean(it.get("title", "")), "summary": clean(it.get("description", ""))[:600],
                    "url": it.get("url", ""), "ts": _ts_from_any(str(ts)) if ts else None,
                    "hint_type": BYBIT_TYPE.get(key), "tags": it.get("tags") or []})
    return [x for x in out if x["title"] and x["ts"]]


def parse_okx(data: dict) -> list[dict]:
    """OKX 公告：data 可能是 [{details:[{title,annType,pTime,url}], totalPage}]，也可能直接是項目列表。"""
    rows = []
    for blk in (data or {}).get("data") or []:
        rows += blk.get("details") if isinstance(blk, dict) and isinstance(blk.get("details"), list) else [blk]
    out = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        ann = str(it.get("annType") or "")
        hint = "delisting" if "delist" in ann else "listing" if "listing" in ann else None
        out.append({"source": "okx", "title": clean(it.get("title", "")), "summary": "", "url": it.get("url", ""),
                    "ts": _ts_from_any(str(it.get("pTime") or it.get("businessPTime") or "")), "hint_type": hint})
    return [x for x in out if x["title"] and x["ts"]]


def parse_cryptopanic(data: dict) -> list[dict]:
    out = []
    for it in (data or {}).get("results") or []:
        cur = [c.get("code") for c in it.get("currencies") or [] if c.get("code")]
        out.append({"source": "cryptopanic", "title": clean(it.get("title", "")), "summary": "",
                    "url": it.get("url") or it.get("original_url") or "", "ts": _ts_from_any(it.get("published_at")),
                    "coins_hint": cur})
    return [x for x in out if x["title"] and x["ts"]]


def fetch_all(cfg: dict, workers: int = 6) -> tuple[list[dict], dict, list[str]]:
    """回傳 (新聞項目, 失敗的來源 {名稱: 原因}, 成功的來源)。個別來源失敗不影響其他來源。"""
    ncfg = cfg["news"]
    jobs = []
    for f in ncfg["feeds"]:
        if f.get("enabled", True):
            jobs.append(f)
    token = os.environ.get("CRYPTOPANIC_TOKEN")
    if token and ncfg.get("cryptopanic_url"):
        jobs.append({"name": "cryptopanic", "kind": "cryptopanic", "url": ncfg["cryptopanic_url"].format(token=token),
                     "tier": "aggregator"})

    def one(f):
        try:
            if f["kind"] == "rss":
                return f, parse_feed(sc.http_get(f["url"], raw=True, retries=2, timeout=15) or b"", f["name"]), None
            data = sc.http_get(f["url"], retries=2, timeout=15)
            parser = {"bybit": parse_bybit, "okx": parse_okx, "cryptopanic": parse_cryptopanic}[f["kind"]]
            return f, parser(data), None
        except Exception as e:  # noqa: BLE001  來源壞掉就記錄、繼續
            msg = str(e).split("。")[0]  # http_get 的提示是給交易所的（改用 --exchange…），新聞來源只留原因
            if "token=" in msg:
                msg = re.sub(r"auth_token=[^&\s]+", "auth_token=***", msg)
            return f, [], msg[:200]

    items, errors, ok = [], {}, []
    with ThreadPoolExecutor(workers) as pool:
        for f, got, err in pool.map(one, jobs):
            if err:
                errors[f["name"]] = err
                continue
            ok.append(f["name"])
            for it in got:
                it["tier"] = f.get("tier", "media")
            items += got
    # 同一則新聞多個來源轉載：標題相同只留一次（保留較高層級的來源）
    rank = {"official": 0, "media": 1, "aggregator": 2}
    seen = {}
    for it in sorted(items, key=lambda x: rank.get(x["tier"], 3)):
        k = re.sub(r"\W+", "", it["title"].lower())[:90]
        seen.setdefault(k, it)
    return list(seen.values()), errors, ok


# ----------------------------------------------------------------------------------------------
# 對應到幣、分類、打分
# ----------------------------------------------------------------------------------------------

def load_aliases(cfg: dict) -> dict:
    p = HERE / "news_aliases.json"
    al = json.loads(p.read_text(encoding="utf-8"))["aliases"] if p.exists() else {}
    al.update(cfg.get("news", {}).get("aliases") or {})
    return al


class Matcher:
    """把新聞文字對應到幣。強訊號：$SOL、(SOL)、SOLUSDT、SOL/USDT、SOL-USDT；名稱別名（solana）；
    長度 ≥ 3 的大寫代號整字（不在 STOPWORDS、也不在 ambiguous 清單）。"""

    def __init__(self, coins, aliases: dict, ambiguous=()):
        self.coins = {sc.base_key(c) for c in coins}
        self.ambiguous = {a.upper() for a in ambiguous}
        names = []
        for name, coin in aliases.items():
            if sc.base_key(coin) in self.coins:
                names.append((name, sc.base_key(coin)))
        names.sort(key=lambda x: -len(x[0]))  # 先比對長的（bitcoin cash 先於 bitcoin）
        self.names = [(re.compile(r"(?<![\w$])" + re.escape(n) + r"(?![\w])", re.I), c) for n, c in names]
        self.strong = re.compile(r"(?:\$([A-Z0-9]{2,15})\b|\(([A-Z0-9]{2,15})\)|\b(?:1000|1M|10000|1000000)?([A-Z0-9]{2,15})"
                                 r"(?:USDT|/USDT|-USDT|USDC|/USD\b))")
        self.word = re.compile(r"(?<![\w$])([A-Z][A-Z0-9]{2,14})(?![\w])")

    def match(self, text: str) -> set[str]:
        found = set()
        masked = text
        for rx, coin in self.names:
            if rx.search(masked):
                found.add(coin)
                masked = rx.sub(" ", masked)
        for m in self.strong.finditer(masked):
            t = sc.base_key(next(g for g in m.groups() if g))
            if t in self.coins:
                found.add(t)
        for m in self.word.finditer(masked):
            t = m.group(1)
            if t in self.coins and t not in STOPWORDS and t not in self.ambiguous:
                found.add(t)
        return found


def classify(item: dict) -> tuple[str, str, int]:
    if item.get("hint_type"):
        k = item["hint_type"]
        for key, _zh, d, imp, _ in TAXONOMY:
            if key == k:
                return key, d, imp
    text = (item["title"] + " " + item.get("summary", "")[:300]).lower()
    for key, _zh, d, imp, pats in TAXONOMY:
        if any(re.search(p, text) for p in pats):
            return key, d, imp
    return "general", "unc", 1


def annotate(items: list[dict], coins, cfg: dict, now_ms: float | None = None) -> tuple[dict, list[dict]]:
    """回傳 ({幣: 催化劑摘要}, 全市場（總經）新聞)。"""
    ncfg = cfg["news"]
    now_ms = now_ms or time.time() * 1000
    lookback = ncfg["lookback_hours"] * HOUR_MS
    matcher = Matcher(coins, load_aliases(cfg), ncfg.get("ambiguous_tickers", []))
    tier_w = ncfg["tier_weight"]
    per, macro = {}, []
    for it in items:
        age_ms = now_ms - it["ts"]
        if age_ms > lookback or age_ms < -HOUR_MS:  # 太舊，或時間在未來（時鐘錯）
            continue
        typ, direction, impact = classify(it)
        age_h = max(age_ms, 0) / HOUR_MS
        w = tier_w.get(it["tier"], 0.5) * impact * 0.5 ** (age_h / ncfg["half_life_hours"])
        hits = matcher.match(it["title"] + " " + it.get("summary", ""))
        hits |= {sc.base_key(c) for c in it.get("coins_hint", []) if sc.base_key(c) in matcher.coins}
        rec = {"type": typ, "type_zh": TYPE_ZH[typ], "direction": direction, "impact": impact, "weight": round(w, 3),
               "age_h": round(age_h, 1), "source": it["source"], "tier": it["tier"], "title": it["title"][:200],
               "url": it["url"], "time_utc": datetime.fromtimestamp(it["ts"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")}
        if not hits:
            if typ == "macro":
                macro.append(rec)
            continue
        if len(hits) > ncfg["max_coins_per_item"]:  # 一次提到一堆幣的綜合報導（行情回顧）不算個別催化劑
            continue
        for c in hits:
            per.setdefault(c, []).append(rec)
    out = {}
    for c, recs in per.items():
        recs.sort(key=lambda r: -r["weight"])
        fresh = [r for r in recs if r["age_h"] <= ncfg["fresh_hours"]]
        official_delist = [r for r in recs if r["type"] == "delisting" and r["tier"] == "official"]
        media_delist = [r for r in recs if r["type"] == "delisting" and r["tier"] != "official"]
        hacks = [r for r in recs if r["type"] == "hack" and r["age_h"] <= ncfg["hack_avoid_hours"]]
        strong = [r for r in fresh if r["impact"] >= 2 and r["direction"] != "neg"]
        sources = {r["source"] for r in fresh}
        delisting = bool(official_delist) or len({r["source"] for r in media_delist}) >= 2
        if delisting or hacks or media_delist:  # 單一媒體的下架消息：標記避開，但不剔除（等第二來源或官方公告）
            tag = "AVOID"
        elif strong or (fresh and len(sources) >= 2):
            tag = "FOCUS"
        elif fresh:
            tag = "NEWS"
        else:
            tag = "OLD"
        out[c] = {
            "score": round(sum(r["weight"] for r in recs), 3),
            "n": len(recs), "n_fresh": len(fresh), "sources": sorted({r["source"] for r in recs}),
            "tag": tag, "delisting": delisting, "hack": bool(hacks),
            "top": recs[:3],
            "types": sorted({r["type"] for r in fresh}),
        }
    macro.sort(key=lambda r: -r["weight"])
    return out, macro[:8]


TAG_ZH = {"FOCUS": "焦點", "AVOID": "避開", "NEWS": "有新聞", "OLD": "舊聞"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("coins", nargs="*")
    ap.add_argument("--macro", action="store_true")
    ap.add_argument("--config")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    cfg = sc.load_config(a.config)
    items, errors, ok = fetch_all(cfg)
    coins = [c.upper() for c in a.coins] or list(set(load_aliases(cfg).values()))
    per, macro = annotate(items, coins, cfg)
    print(f"新聞來源：成功 {', '.join(ok) or '無'}；失敗 {', '.join(errors) or '無'}；{len(items)} 則")
    for k, v in errors.items():
        print(f"  ! {k}: {v}")
    if not a.macro:
        for c in sorted(per, key=lambda c: -per[c]["score"]):
            v = per[c]
            print(f"\n{c}  {TAG_ZH[v['tag']]}  分數 {v['score']}  （48h {v['n']} 則、24h {v['n_fresh']} 則）")
            for r in v["top"]:
                print(f"  [{r['type_zh']}] {r['time_utc']} UTC {r['source']}：{r['title']}\n      {r['url']}")
    print("\n總經 / 全市場：")
    for r in macro:
        print(f"  {r['time_utc']} UTC {r['source']}：{r['title']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"coins": per, "macro": macro, "errors": errors, "ok": ok},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
