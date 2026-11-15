"""一輪執行週期（排程器每根 5m 收盤 +20 秒呼叫）：消息面（每 30 分鐘）→ 掃描 → 篩選 + 即時訊號 → 風控狀態。"""
from __future__ import annotations
import json, traceback
from datetime import datetime, timezone
from company.paths import EXEC, load_json, write_json
from exec import news, risk, scanner, signals


def run() -> dict:
    out = {"started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "steps": {}}
    try:
        c = load_json(news.CACHE, {})
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(c["fetched_at"])).total_seconds() if c else 1e9
        st = news.refresh() if age > 1800 or not c.get("ok") and age > 300 else news.status()
        out["steps"]["news"] = {"blocked": st["blocked"], "reasons": st.get("reasons", [])[:5]}
    except Exception as e:
        out["steps"]["news"] = {"error": repr(e)}
    for name, fn in (("scan", lambda: {"n": len(scanner.scan()["universe"])}),
                     ("signals", lambda: {k: v for k, v in signals.run().items() if k in ("tradable_count", "risk_blocked")} | {"n": len(signals.latest()["signals"])}),
                     ("risk", lambda: {"blocked": risk.state()["new_entries_blocked"]})):
        try:
            out["steps"][name] = fn()
        except Exception as e:
            out["steps"][name] = {"error": repr(e), "trace": traceback.format_exc()[-800:]}
    out["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(EXEC / "state" / "cycle.json", out)
    return out


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
