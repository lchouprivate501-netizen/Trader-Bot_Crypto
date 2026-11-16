"""SOLMomentumEA - SOL spot momentum EA (FreqAI volatility-sized).

Built from earlier chart research on a SOL grid bot (not part of this project): SOL's trends start and end abruptly, and the
grid lost money by buying every failed breakout and stopping out near the lows. This EA buys
only confirmed breakouts while the ~50-day EMA is rising, sizes them small (SOL's volatility
is 2x BTC's) and trails a wide chandelier stop so it can sit through SOL-sized pullbacks.
"""

from __future__ import annotations

from EABase import EABase


class SOLMomentumEA(EABase):
    # Frozen after development-period tuning (2021-06-01 .. 2024-12-12), before validation.
    EA = {
        **EABase.EA,
        "trend_ema": 1200,  # ~50 days, must be rising
        "ema_band": 0.02,
        "slope_h": 24,
        "breakout_h": 720,  # 30-day high (plateau 720-960h)
        "trail_k": 12.0,  # SOL needs the widest stop (plateau 10-16)
        "risk_per_trade": 0.10,  # dev max drawdown ~22%
    }
