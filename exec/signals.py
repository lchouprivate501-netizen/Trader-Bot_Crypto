"""執行部：篩選（shortlist）與即時訊號。
- shortlist：掃描結果 × 每個策略的 near() 分數，列出快要觸發的幣。
- live_signals：對最新一根「已收盤」5m K 線跑策略；PASSED/LIVE 策略的訊號 tradable=true，其餘為 shadow（只做前測紀錄，不得下單）。
訊號檔：exec/signals/<strategy>__<SYM>.json，彙總 exec/signals/latest.json，歷史 exec/signals/history.jsonl。"""
from __future__ import annotations
import json
from datetime import timedelta, datetime, timezone
import pandas as pd
from company import okx
from company.paths import EXEC, SIGNALS, load_json, write_json
from rnd import registry
from rnd.strategies import ALL, get
from rnd.strategies.base import attach_htf
from exec import risk

SHORT = EXEC / "state" / "shortlist.json"


def _frames(sym):
    d5 = okx.recent(sym, "5m", 300)
    d5 = d5[d5.confirm == 1].reset_index(drop=True)
    d1 = okx.recent(sym, "1h", 300)
    d1 = d1[d1.confirm == 1].reset_index(drop=True)
    return attach_htf(d5, d1)


def _params(name):
    s = registry.load()["strategies"].get(name, {})
    mod = get(name)
    p = dict(mod.DEFAULTS); p.update(s.get("params") or {})
    return p, s.get("status", "coded")


def _symbols():
    scan = load_json(EXEC / "state" / "scan.json", {})
    return [r["symbol"] for r in scan.get("universe", [])]


def run(symbols: list[str] | None = None) -> dict:
    symbols = symbols or _symbols()
    now = datetime.now(timezone.utc)
    st = risk.state()
    sigs, short = [], []
    for f in SIGNALS.glob("*__*.json"):
        f.unlink()
    for sym in symbols:
        try:
            df = _frames(sym)
        except Exception as e:
            short.append({"symbol": sym, "error": str(e)}); continue
        bar_close = df.ts.iloc[-1] + pd.Timedelta(minutes=5)
        for name in ALL:
            mod = get(name)
            p, status = _params(name)
            tradable = status in ("PASSED", "LIVE")
            try:
                score = mod.near(df, p) if hasattr(mod, "near") else None
            except Exception:
                score = None
            if score and score >= 0.6:
                short.append({"symbol": sym, "strategy": name, "near_score": score, "tradable": tradable, "status": status})
            sg = mod.signals(df, p).iloc[-1]
            side = "long" if sg.long else ("short" if sg.short else None)
            if not side:
                continue
            entry = float(df.close.iloc[-1])
            sl = float(sg.sl_long if side == "long" else sg.sl_short)
            tp = float(sg.tp_long if side == "long" else sg.tp_short)
            sz = risk.size(st["equity_usdt"], entry, sl) if st["equity_usdt"] else None
            s = {"id": f"{name}-{sym}-{bar_close:%Y%m%dT%H%M}-{side}", "strategy": name, "status": status, "tradable": tradable,
                 "symbol": sym, "pionex_pair": f"{sym}/USDT 永續", "side": side, "entry": entry, "sl": sl, "tp": tp,
                 "rr": round(abs(tp - entry) / abs(entry - sl), 2), "bar_close_utc": bar_close.isoformat(),
                 "valid_until_utc": (bar_close + timedelta(minutes=5)).isoformat(), "max_hold_minutes": int(p.get("max_hold", 36)) * 5,
                 "size": sz, "leverage": 2, "margin_mode": "isolated", "generated_at": now.isoformat(timespec="seconds")}
            write_json(SIGNALS / f"{name}__{sym}.json", s)
            with (SIGNALS / "history.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")
            sigs.append(s)
    short.sort(key=lambda r: -(r.get("near_score") or 0))
    write_json(SHORT, {"at": now.isoformat(timespec="seconds"), "items": short})
    out = {"at": now.isoformat(timespec="seconds"), "risk_blocked": st["new_entries_blocked"], "risk_blocks": st["blocks"],
           "passed_strategies": registry.passed(), "signals": sigs,
           "tradable_count": sum(1 for s in sigs if s["tradable"])}
    write_json(SIGNALS / "latest.json", out)
    return out


def shortlist() -> dict:
    return load_json(SHORT, {"items": [], "note": "尚未產生；排程器每 5 分鐘更新"})


def latest() -> dict:
    return load_json(SIGNALS / "latest.json", {"signals": [], "note": "尚未產生"})
