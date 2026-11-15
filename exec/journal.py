"""執行部「交易紀錄」角色：寫帳本（成交）、權益、以及每日 journal/YYYY-MM-DD.md 與 journal/events.jsonl。
績效最後回流研發部（rnd 讀 journal/events.jsonl 做策略修正）。"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from company.paths import JOURNAL
from exec import ledger, mode

TPE = timezone(timedelta(hours=8))


def write(kind: str, data: dict) -> dict:
    """kind: fill（開/平倉成交，寫 ledger）| equity（記錄交易所權益）| note（決策/觀察）| skip（放棄訊號與原因）."""
    now = datetime.now(timezone.utc)
    m = mode.get()
    rec = {"at": now.isoformat(timespec="seconds"), "kind": kind, "mode": m, **data}
    if kind == "fill":
        need = ["position_id", "pair", "side", "action", "price"]
        miss = [k for k in need if not data.get(k)]
        if miss:
            return {"ok": False, "error": f"fill 缺少欄位 {miss}"}
        data = {**data, "mode": data.get("mode", m)}
        data.setdefault("fill_id", f"{m[0]}-{now:%Y%m%dT%H%M%S}-{data['pair'].split('/')[0]}")
        rec["ledger_row"] = ledger.append(data)
    elif kind == "equity":
        if "equity_usdt" not in data:
            return {"ok": False, "error": "equity 需要 equity_usdt"}
        try:
            from company.exchange import active_name
            default_src = f"{active_name() or 'exchange'}_browser"
        except Exception:
            default_src = "exchange_browser"
        rec["equity"] = ledger.record_equity(float(data["equity_usdt"]), m, data.get("source", default_src))
    elif kind not in ("note", "skip"):
        return {"ok": False, "error": "kind 必須是 fill/equity/note/skip"}
    with (JOURNAL / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    day = JOURNAL / f"{now.astimezone(TPE):%Y-%m-%d}.md"
    line = f"- {now.astimezone(TPE):%H:%M} 台北 [{m}] {kind}: " + ", ".join(f"{k}={v}" for k, v in data.items() if k != "ledger_row")
    with day.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return {"ok": True, **rec}
