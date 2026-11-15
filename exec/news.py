"""執行部「消息面」角色：找出危險、不可交易的時段。失敗即封鎖（fail-closed）。
來源（免費、免金鑰）：
- ForexFactory 週曆 JSON（nfs.faireconomy.media）：USD 高影響事件，事件前 30 分到後 60 分禁止新單。
- OKX 公告 API（公開）：近 48h 涉及標的的下架/遷移/交易更新 → 該幣 24h 禁止新單；含 maintenance/upgrade 的公告 → 全部暫停 ±60 分。
快取在 exec/state/news.json；超過 6 小時沒成功更新就視為危險。"""
from __future__ import annotations
import re
from datetime import datetime, timedelta, timezone
import requests
from company.paths import EXEC, load_json, pionex_perps, write_json

CACHE = EXEC / "state" / "news.json"
FF = ["https://nfs.faireconomy.media/ff_calendar_thisweek.json", "https://nfs.faireconomy.media/ff_calendar_nextweek.json"]
OKX_ANN = "https://www.okx.com/api/v5/support/announcements"
BEFORE, AFTER = timedelta(minutes=30), timedelta(minutes=60)
MAX_AGE = timedelta(hours=6)
UTC = timezone.utc


def _now():
    return datetime.now(UTC)


def refresh() -> dict:
    now = _now()
    windows, sources = [], {}
    events = []
    ok_cal = False
    for url in FF:
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "trading-company/1.0"})
            r.raise_for_status()
            events += r.json(); ok_cal = True
            sources[url] = "ok"
        except Exception as e:  # nextweek file is often missing → only thisweek is required
            sources[url] = f"error: {e.__class__.__name__}"
    if not sources.get(FF[0]) == "ok":
        ok_cal = False
    dates = []
    for ev in events:
        try:
            dates.append(datetime.fromisoformat(ev["date"]))
        except Exception:
            pass
    coverage_end = None
    if dates:
        last = max(dates)  # FF week file runs Sun–Sat (US Eastern); coverage ends the next Sunday 00:00 local
        coverage_end = (last + timedelta(days=(6 - last.weekday()) % 7 or 7)).replace(hour=0, minute=0, second=0).astimezone(UTC)
        if coverage_end < now:
            ok_cal = False
            sources["coverage"] = f"calendar stale: covers until {coverage_end.isoformat()}"
    for ev in events:
        if ev.get("country") != "USD" or ev.get("impact") != "High":
            continue
        try:
            t = datetime.fromisoformat(ev["date"]).astimezone(UTC)
        except Exception:
            continue
        if t + AFTER < now - timedelta(hours=1):
            continue
        windows.append({"start": (t - BEFORE).isoformat(), "end": (t + AFTER).isoformat(), "scope": "ALL", "reason": f"USD 高影響：{ev.get('title')}", "source": "forexfactory"})
    ok_ann = False
    syms = set(pionex_perps())
    try:
        r = requests.get(OKX_ANN, params={"page": 1}, timeout=15)
        r.raise_for_status()
        anns = r.json()["data"][0]["details"]
        ok_ann = True
        sources["okx_announcements"] = "ok"
        for a in anns:
            pt = datetime.fromtimestamp(int(a.get("businessPTime") or a["pTime"]) / 1000, UTC)
            title = a["title"]
            if re.search(r"maintenance|upgrade|system", title, re.I) and pt > now - timedelta(hours=2):
                windows.append({"start": (pt - timedelta(minutes=60)).isoformat(), "end": (pt + timedelta(minutes=60)).isoformat(),
                                "scope": "ALL", "reason": f"OKX 公告：{title}", "source": "okx"})
            if now - pt < timedelta(hours=48) and a.get("annType") in ("announcements-delistings", "trading-updates-us-aus", "announcements-new-listings"):
                for s in syms:
                    if re.search(rf"\b{s}\b", title):
                        windows.append({"start": pt.isoformat(), "end": (pt + timedelta(hours=24)).isoformat(), "scope": s,
                                        "reason": f"OKX 公告涉及 {s}：{title}", "source": "okx"})
    except Exception as e:
        sources["okx_announcements"] = f"error: {e.__class__.__name__}"
    out = {"fetched_at": now.isoformat(timespec="seconds"), "ok": ok_cal and ok_ann, "calendar_ok": ok_cal, "announcements_ok": ok_ann,
           "calendar_coverage_end": coverage_end.isoformat() if coverage_end else None, "sources": sources, "windows": sorted(windows, key=lambda w: w["start"])}
    prev = load_json(CACHE, {})
    if not out["ok"] and prev.get("ok"):
        out["last_good"] = prev.get("fetched_at")
    write_json(CACHE, out)
    return status()


def status(symbol: str | None = None) -> dict:
    now = _now()
    c = load_json(CACHE)
    if not c:
        return {"blocked": True, "reason": "消息面尚未更新（fail-closed）", "windows": []}
    age = now - datetime.fromisoformat(c["fetched_at"])
    active = [w for w in c["windows"] if datetime.fromisoformat(w["start"]) <= now <= datetime.fromisoformat(w["end"])
              and (w["scope"] == "ALL" or symbol is None or w["scope"] == symbol)]
    upcoming = [w for w in c["windows"] if now < datetime.fromisoformat(w["start"]) <= now + timedelta(hours=24)]
    reasons = []
    if not c.get("ok"):
        reasons.append(f"消息來源失敗（fail-closed）：{c.get('sources')}")
    if age > MAX_AGE:
        reasons.append(f"消息面資料過舊 {age}（fail-closed）")
    reasons += [w["reason"] for w in active]
    return {"blocked": bool(reasons), "reasons": reasons, "active": active, "upcoming_24h": upcoming,
            "fetched_at": c["fetched_at"], "now": now.isoformat(timespec="seconds")}


if __name__ == "__main__":
    import json; print(json.dumps(refresh(), ensure_ascii=False, indent=2))
