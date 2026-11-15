"""研發部「看報表」角色：把 nautilus 的平倉紀錄轉成上線門檻檢核表（JSON + Markdown）。"""
from __future__ import annotations
import pandas as pd
from company.paths import criteria


def trades_from_positions(pos: pd.DataFrame) -> pd.DataFrame:
    if pos is None or pos.empty:
        return pd.DataFrame(columns=["pair", "opened", "closed", "side", "pnl", "fee", "notional"])
    p = pos[pos.ts_closed.notna()].copy()
    p = p.drop_duplicates(subset=["instrument_id", "ts_opened"])
    f = lambda x: float(str(x).split()[0])
    out = pd.DataFrame({
        "pair": p.instrument_id.astype(str).str.replace("USDT-PERP.OKX", "", regex=False),
        "opened": pd.to_datetime(p.ts_opened, utc=True), "closed": pd.to_datetime(p.ts_closed, utc=True),
        "side": p.entry.astype(str),
        "pnl": p.realized_pnl.map(f),
        "fee": p.commissions.map(lambda c: sum(f(x) for x in c) if isinstance(c, (list, tuple)) else f(c)),
        "notional": p.peak_qty.astype(float) * p.avg_px_open.astype(float)})
    return out.sort_values("closed").reset_index(drop=True)


def evaluate(tr: pd.DataFrame, start_equity: float) -> dict:
    c = criteria()
    n = len(tr)
    gp, gl = tr.pnl[tr.pnl > 0].sum(), -tr.pnl[tr.pnl < 0].sum()
    pf = float(gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    eq = start_equity + tr.pnl.cumsum()
    peak = pd.concat([pd.Series([start_equity]), eq]).cummax().iloc[1:].values
    mdd = float(((peak - eq.values) / peak).max() * 100) if n else 0.0
    net = float(tr.pnl.sum())
    avg_net = net / n if n else 0.0
    avg_fee = float(tr.fee.mean()) if n else 0.0
    by_pair = tr.groupby("pair").pnl.agg(["count", "sum"]).round(2) if n else pd.DataFrame()
    by_month = tr.groupby(tr.closed.dt.strftime("%Y-%m")).pnl.agg(["count", "sum"]).round(2) if n else pd.DataFrame()
    top2 = float(tr.pnl.nlargest(2).sum()) if n else 0.0
    best_pair = float(by_pair["sum"].max()) if n else 0.0
    best_month = float(by_month["sum"].max()) if n else 0.0
    conc_ok = n > 0 and net - max(best_pair, 0) > 0 and net - max(best_month, 0) > 0 and net - max(top2, 0) > 0
    rows = [
        ("交易筆數 ≥ %d" % c["min_trades"], n, n >= c["min_trades"]),
        ("扣費後獲利因子 ≥ %.1f" % c["min_profit_factor"], round(pf, 3), pf >= c["min_profit_factor"]),
        ("最大回撤 ≤ %.0f%%" % c["max_drawdown_pct"], round(mdd, 2), mdd <= c["max_drawdown_pct"]),
        ("平均每筆淨利 ≥ %.0f× 來回手續費" % c["min_avg_net_to_roundtrip_fee"],
         f"{avg_net:.3f} vs {c['min_avg_net_to_roundtrip_fee']}×{avg_fee:.3f}", avg_net >= c["min_avg_net_to_roundtrip_fee"] * avg_fee and n > 0),
        ("不靠單一幣種/月份/前兩筆撐起", f"net {net:.2f}; best pair {best_pair:.2f}; best month {best_month:.2f}; top2 {top2:.2f}", bool(conc_ok)),
    ]
    return {
        "trades": n, "net_pnl": round(net, 2), "return_pct": round(net / start_equity * 100, 2), "profit_factor": round(pf, 3),
        "max_drawdown_pct": round(mdd, 2), "win_rate": round(float((tr.pnl > 0).mean() * 100), 2) if n else 0.0,
        "avg_net_per_trade": round(avg_net, 4), "avg_roundtrip_fee": round(avg_fee, 4), "fees_total": round(float(tr.fee.sum()), 2),
        "criteria": [{"criterion": a, "value": b, "pass": bool(p)} for a, b, p in rows],
        "passed": all(p for _, _, p in rows),
        "by_pair": by_pair.reset_index().to_dict("records") if n else [],
        "by_month": by_month.reset_index().rename(columns={"closed": "month"}).to_dict("records") if n else [],
    }


def to_markdown(name: str, meta: dict, ins: dict, oos: dict) -> str:
    L = [f"# 策略報告：{name}", "", f"- 產生時間：{meta['generated']}", f"- 資料：{meta['data']}",
         f"- 樣本內（優化用，前 70%）：{meta['is_range']}", f"- 樣本外（從未用於調參，後 30%）：{meta['oos_range']}",
         f"- 參數：`{meta['params']}`（優化 {meta['trials']} 次試驗，上限 300）", f"- 手續費：{meta['fee']*100:.3f}%/邊（maker=taker，保守）",
         f"- 引擎：nautilus_trader {meta['nautilus']}，組合層級（最多 3 倉、每筆風險 0.5%、2x 逐倉）", "",
         f"## 結論：{'PASSED ✅ 可自動轉實盤' if oos['passed'] else 'REJECTED ❌ 不得上線'}", "",
         "## 樣本外上線門檻", "", "| 門檻 | 實際 | 結果 |", "|---|---|---|"]
    for r in oos["criteria"]:
        L.append(f"| {r['criterion']} | {r['value']} | {'PASS' if r['pass'] else 'FAIL'} |")
    L += ["", "## 摘要", "", "| | 樣本內 | 樣本外 |", "|---|---|---|"]
    for k in ["trades", "net_pnl", "return_pct", "profit_factor", "max_drawdown_pct", "win_rate", "avg_net_per_trade", "avg_roundtrip_fee", "fees_total"]:
        L.append(f"| {k} | {ins[k]} | {oos[k]} |")
    L += ["", "## 樣本外：各幣種", "", "| 幣種 | 筆數 | 淨利 USDT |", "|---|---|---|"]
    L += [f"| {r['pair']} | {r['count']} | {r['sum']} |" for r in oos["by_pair"]]
    L += ["", "## 樣本外：各月份", "", "| 月份 | 筆數 | 淨利 USDT |", "|---|---|---|"]
    L += [f"| {r['month']} | {r['count']} | {r['sum']} |" for r in oos["by_month"]]
    L += ["", f"風控攔截次數（樣本外）：{meta.get('oos_blocked')}", ""]
    return "\n".join(L)
