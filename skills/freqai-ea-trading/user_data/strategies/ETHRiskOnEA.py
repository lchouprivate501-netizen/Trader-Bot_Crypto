"""ETHRiskOnEA - ETH spot trend-following EA that only trades while BTC is risk-on.

Built from earlier chart research on an ETH grid bot (not part of this project): the one robust ETH-specific edge was the BTC
risk-on filter (ETH only in BTC's ~100-day uptrend). Entries are ETH breakouts above its own
~50-day EMA inside that regime; exits are a chandelier stop, ETH's trend ending, or BTC
turning risk-off.
"""

from __future__ import annotations

from EABase import EABase


class ETHRiskOnEA(EABase):
    # Frozen after development-period tuning (2021-06-01 .. 2024-12-12), before validation.
    EA = {
        **EABase.EA,
        "trend_ema": 1200,  # ETH's own ~50-day trend
        "ema_band": 0.02,
        "ref_trend_ema": 2400,  # BTC risk-on: BTC above its ~100-day EMA
        "breakout_h": 480,  # 20-day high (flat plateau 240-720h)
        "trail_k": 10.0,  # plateau 8-12
        "risk_per_trade": 0.10,  # dev max drawdown ~22%
    }
