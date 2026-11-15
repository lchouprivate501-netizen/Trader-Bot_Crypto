"""模式：PAPER（預設）/ LIVE / HALT，存在 state/mode。
- LIVE：只有登記簿裡至少一個策略是 PASSED（或 LIVE）才允許。
- HALT、PAPER：任何時候都允許（更安全的方向）。"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from company.paths import STATE
from rnd import registry

MODE = STATE / "mode"
HIST = STATE / "mode_history.jsonl"
VALID = ("PAPER", "LIVE", "HALT")


def get() -> str:
    try:
        m = MODE.read_text().strip().upper()
        return m if m in VALID else "HALT"
    except FileNotFoundError:
        return "PAPER"


def set_mode(mode: str, reason: str, actor: str = "Trader") -> dict:
    mode = mode.strip().upper()
    if mode not in VALID:
        return {"ok": False, "error": f"mode must be one of {VALID}"}
    passed = registry.passed()
    if mode == "LIVE" and not passed:
        return {"ok": False, "mode": get(), "error": "拒絕：登記簿沒有 PASSED 策略，不能轉 LIVE"}
    prev = get()
    MODE.write_text(mode + "\n")
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "from": prev, "to": mode, "reason": reason, "actor": actor,
           "passed_strategies": passed}
    with HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if mode == "LIVE":
        for s in passed:
            if registry.load()["strategies"][s]["status"] == "PASSED":
                registry.set_status(s, "LIVE")
    return {"ok": True, **rec}
