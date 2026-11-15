"""執行部「掃描市場」角色：啟用中交易所白名單內，依 OKX 24h 成交額排前 N，並附波動率（24h 振幅、5m ATR%）。"""
from __future__ import annotations
from datetime import datetime, timezone
from company import okx
from company.paths import EXEC, universe, whitelist, write_json
from rnd.strategies.base import atr

OUT = EXEC / "state" / "scan.json"


def scan(top_n: int | None = None) -> dict:
    top_n = top_n or universe()["scan_top_n"]
    allow = set(whitelist())
    rows = []
    for t in okx.tickers():
        iid = t["instId"]
        if not iid.endswith("-USDT-SWAP"):
            continue
        sym = iid.split("-")[0]
        if sym not in allow:
            continue
        last = float(t["last"]); vol_usd = float(t["volCcy24h"]) * last
        hi, lo, op = float(t["high24h"]), float(t["low24h"]), float(t["open24h"])
        rows.append({"symbol": sym, "last": last, "vol24h_usd": round(vol_usd), "range24h_pct": round((hi - lo) / lo * 100, 2),
                     "change24h_pct": round((last - op) / op * 100, 2)})
    rows.sort(key=lambda r: -r["vol24h_usd"])
    rows = rows[:top_n]
    for r in rows:
        try:
            d = okx.recent(r["symbol"], "5m", 100)
            r["atr5m_pct"] = round(float(atr(d, 14).iloc[-1] / d.close.iloc[-1] * 100), 3)
        except Exception:
            r["atr5m_pct"] = None
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "OKX public tickers", "universe": rows}
    write_json(OUT, out)
    return out
