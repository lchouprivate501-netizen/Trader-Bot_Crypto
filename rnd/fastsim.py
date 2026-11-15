"""快速向量化模擬器（只給優化器用）：每個幣種獨立、一次一筆、收盤價進場，
同一根同時碰到停損和停利時算停損（保守）。手續費雙邊 taker。輸出每筆的 R 倍數（扣費後）。
正式數字一律以 nautilus_trader 回測（rnd/engine.py）為準。"""
from __future__ import annotations
import numpy as np
import pandas as pd


def simulate(df: pd.DataFrame, sig: pd.DataFrame, max_hold: int, fee: float) -> pd.DataFrame:
    h, l, c = df.high.values, df.low.values, df.close.values
    ts = df.ts.values
    L, S = sig.long.values, sig.short.values
    out = []
    i, n = 0, len(df)
    while i < n - 1:
        side = 1 if L[i] else (-1 if S[i] else 0)
        if side == 0:
            i += 1; continue
        e = c[i]
        sl = sig.sl_long.values[i] if side == 1 else sig.sl_short.values[i]
        tp = sig.tp_long.values[i] if side == 1 else sig.tp_short.values[i]
        risk = abs(e - sl)
        if not np.isfinite(risk) or risk <= 0:
            i += 1; continue
        exit_px, j = None, i + 1
        end = min(n - 1, i + max_hold)
        while j <= end:
            if side == 1:
                if l[j] <= sl: exit_px = sl; break
                if h[j] >= tp: exit_px = tp; break
            else:
                if h[j] >= sl: exit_px = sl; break
                if l[j] <= tp: exit_px = tp; break
            j += 1
        if exit_px is None:
            j = end; exit_px = c[j]
        gross = side * (exit_px - e)
        fees = fee * (e + exit_px)
        out.append((ts[i], ts[j], side, e, exit_px, (gross - fees) / risk, fees / risk))
        i = j + 1
    return pd.DataFrame(out, columns=["t_in", "t_out", "side", "entry", "exit", "r_net", "r_fee"])
