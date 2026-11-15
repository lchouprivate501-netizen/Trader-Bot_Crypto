"""執行部「風險管控」角色：從帳本強制執行硬性上限（company/risk_caps.json，任何角色都不能放寬）。"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from company.paths import EXEC, risk_caps, write_json
from exec import ledger, mode, news

OUT = EXEC / "state" / "risk.json"


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def state() -> dict:
    caps = risk_caps()
    now = datetime.now(timezone.utc)
    eq_hist = ledger.equity_history()
    equity = eq_hist[-1]["equity_usdt"] if eq_hist else None
    peak = max((e["equity_usdt"] for e in eq_hist), default=None)
    dd = (peak - equity) / peak * 100 if equity and peak else 0.0
    today = now.strftime("%Y-%m-%d")
    cl = ledger.closes()
    day_pnl = sum(_f(r["realized_pnl_usdt"]) for r in cl if r["ts_utc"].startswith(today))
    day_start_eq = (equity - day_pnl) if equity else None
    day_loss_pct = (-day_pnl / day_start_eq * 100) if day_start_eq and day_pnl < 0 else 0.0
    streak, last_loss_ts = 0, None
    for r in cl:
        if _f(r["realized_pnl_usdt"]) < 0:
            streak += 1; last_loss_ts = r["ts_utc"]
            if streak >= caps["max_consecutive_losses"]:
                pause_end = datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00")) + timedelta(hours=caps["consecutive_loss_pause_hours"])
                if pause_end > now:
                    break
                streak = 0
        else:
            streak = 0
    pause_until = None
    if streak >= caps["max_consecutive_losses"] and last_loss_ts:
        pause_until = datetime.fromisoformat(last_loss_ts.replace("Z", "+00:00")) + timedelta(hours=caps["consecutive_loss_pause_hours"])
    op = ledger.open_positions()
    m = mode.get()
    blocks = []
    if m == "HALT": blocks.append("模式為 HALT")
    if equity is None: blocks.append("權益未知：請先 journal_write(kind='equity') 記錄交易所帳戶權益（fail-closed）")
    if dd >= caps["max_drawdown_halt_pct"]: blocks.append(f"回撤 {dd:.2f}% ≥ {caps['max_drawdown_halt_pct']}% → HALT")
    if day_loss_pct >= caps["daily_realized_loss_stop_pct"]: blocks.append(f"今日已實現虧損 {day_loss_pct:.2f}% ≥ {caps['daily_realized_loss_stop_pct']}% → 今日停新單")
    if pause_until and pause_until > now: blocks.append(f"連虧 {caps['max_consecutive_losses']} 筆，暫停到 {pause_until.isoformat()}")
    if len(op) >= caps["max_open_positions"]: blocks.append(f"已有 {len(op)} 個持倉（上限 {caps['max_open_positions']}）")
    out = {"at": now.isoformat(timespec="seconds"), "mode": m, "equity_usdt": equity, "peak_equity_usdt": peak, "drawdown_pct": round(dd, 2),
           "today_realized_pnl_usdt": round(day_pnl, 4), "today_loss_pct": round(day_loss_pct, 2), "loss_streak": streak,
           "pause_until": pause_until.isoformat() if pause_until else None, "open_positions": op, "new_entries_blocked": bool(blocks),
           "blocks": blocks, "caps": caps}
    if dd >= caps["max_drawdown_halt_pct"] and m != "HALT":
        mode.set_mode("HALT", f"risk: drawdown {dd:.2f}%", actor="risk_manager")
        out["mode"] = "HALT"
    write_json(OUT, out)
    return out


def size(equity: float, entry: float, sl: float) -> dict:
    from company.exchange import taker_fee
    caps = risk_caps()
    fee = taker_fee()
    risk_usdt = equity * caps["max_risk_per_trade_pct"] / 100
    dist = abs(entry - sl)
    fee_per_unit = entry * 2 * fee  # conservative round-trip taker
    denom = dist + fee_per_unit
    qty_risk = risk_usdt / denom if denom > 0 else 0.0
    qty_margin = equity * caps["max_single_coin_margin_pct"] / 100 * caps["leverage"] / entry
    qty = min(qty_risk, qty_margin)
    return {"qty": qty, "notional_usdt": round(qty * entry, 4), "margin_usdt": round(qty * entry / caps["leverage"], 4),
            "risk_usdt": round(qty * dist, 4), "roundtrip_fee_usdt": round(qty * fee_per_unit, 4),
            "taker_fee": fee, "limited_by": "risk" if qty_risk <= qty_margin else "margin_cap", "leverage": caps["leverage"]}


def check(trade: dict) -> dict:
    """trade: {pair|symbol, side, entry, sl, tp?, qty?, leverage?, margin_mode?}. Returns approved + max_qty + reasons."""
    caps = risk_caps()
    st = state()
    sym = (trade.get("symbol") or trade.get("pair") or "").split("/")[0].replace("USDT", "").replace("-", "").upper()
    reasons = list(st["blocks"])
    nw = news.status(sym)
    if nw["blocked"]:
        reasons += [f"消息面：{r}" for r in nw["reasons"]]
    side = str(trade.get("side", "")).lower()
    entry, sl = _f(trade.get("entry")), _f(trade.get("sl"))
    if side not in ("long", "short"): reasons.append("side 必須是 long 或 short")
    if entry <= 0 or sl <= 0: reasons.append("entry/sl 必須 > 0")
    elif (side == "long" and sl >= entry) or (side == "short" and sl <= entry): reasons.append("停損方向錯誤")
    lev = _f(trade.get("leverage"), caps["leverage"])
    if lev != caps["leverage"]: reasons.append(f"槓桿必須是 {caps['leverage']}x（收到 {lev}）")
    if str(trade.get("margin_mode", "isolated")).lower() != "isolated": reasons.append("必須逐倉 isolated")
    if any(p["pair"].split("/")[0].upper() == sym for p in st["open_positions"]): reasons.append(f"{sym} 已有持倉")
    sz = size(st["equity_usdt"], entry, sl) if st["equity_usdt"] and entry > 0 and sl > 0 and entry != sl else None
    q = _f(trade.get("qty"), 0)
    if sz and q > 0 and q > sz["qty"] * 1.0001:
        reasons.append(f"數量 {q} 超過上限 {sz['qty']:.6f}（{sz['limited_by']}）")
    return {"approved": not reasons, "symbol": sym, "reasons": reasons, "sizing": sz, "mode": st["mode"], "equity_usdt": st["equity_usdt"]}
