"""ETHFuturesEA - ETH USDT-M perpetual EA: the validated ETHRiskOnEA long side plus a short side.

Long parameters are ETHRiskOnEA's frozen values (unchanged). Short parameters (s_*) are researched
on the development period only; see references/futures-validation-protocol.md.
"""

from __future__ import annotations

from ETHRiskOnEA import ETHRiskOnEA
from FuturesEABase import FuturesEABase


class ETHFuturesEA(FuturesEABase):
    # Short side frozen after development-period research (2021-06-01 .. 2024-12-12), before validation.
    # One shared design for all three coins: the short trend EMA is the long side's own EMA, the EMA must
    # have been falling for 30 days, and shorts use a tight 3x daily-sigma chandelier stop (bear-market
    # rallies are violent). Only the breakdown lookback is coin-specific. See references/futures-design.md.
    EA = {
        **FuturesEABase.EA,
        **ETHRiskOnEA.EA,  # long side: frozen spot EA parameters (unchanged)
        "short": True,
        "s_trend_ema": 1200,  # = the long side's trend EMA
        "s_ema_band": ETHRiskOnEA.EA["ema_band"],
        "s_slope_h": 720,  # EMA lower than 30 days ago
        "s_cross": 0,
        "s_breakout_h": 360,
        "s_trail_k": 3.0,
        "s_init_k": 3.0,
        "s_risk_per_trade": 0.10,  # = the long side's risk per trade
    }
    # Parameters chosen on the development period (V4 perturbs each by +-25%).
    TUNED = ["s_trend_ema", "s_slope_h", "s_breakout_h", "s_trail_k", "s_risk_per_trade"]
