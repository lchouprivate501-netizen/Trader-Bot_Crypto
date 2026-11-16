"""BTCTrendEA - BTC spot trend-following EA (FreqAI volatility-sized).

Built from the chart research on the BTC grid: its profit came almost entirely from holding
a core position above the ~100-day EMA, and its out-of-sample loss came from exiting too late
in a fast drop (the EMA cross lagged ~25% behind the top). This EA keeps the slow trend
filter for entries but replaces the slow exit with a chandelier stop from the highest price.
"""

from __future__ import annotations

from EABase import EABase


class BTCTrendEA(EABase):
    # Frozen after development-period tuning (2021-06-01 .. 2024-12-12), before validation.
    EA = {
        **EABase.EA,
        "trend_ema": 2400,  # ~100 days
        "ema_band": 0.02,
        "breakout_h": 240,  # 10-day high (plateau: 240h beat 480/720h for stops 8-12)
        "trail_k": 10.0,  # stop 10 x daily sigma below the high (~20% for BTC); plateau 8-12
        "risk_per_trade": 0.10,  # dev max drawdown ~17%
    }
