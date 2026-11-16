"""BTCAccumGridAI - BTC spot accumulation grid steered by FreqAI.

Why this shape for BTC
* Lowest volatility of the three (annualised ~45-55% since 2023) and the deepest book:
  tight, many-lot grids are fee-efficient and fill reliably.
* Strongest and most persistent long-term drift: a core position held during the bull
  regime captures the trend that a pure grid would sell too early.
* Spot, long-only: no funding payments on a structurally long book, no liquidation.

Logic
* Session opens when price is above the slow EMA (~100 days, +3% band) and FreqAI's
  predicted drift z-score is not bearish; it holds a core (core_frac) plus up to max_lots
  grid lots.
* Grid step = step_mult x FreqAI-predicted hourly sigma, clipped to [step_min, step_max].
* New lots only while FreqAI does not predict a strong down-drift (add_z).
* New lots pause when FreqAI predicts a volatility spike (vr_max).
* Session ends on regime_off (price below the EMA band *and* bearish drift z) or on a grid
  break (grid full / adds blocked and price break_steps below the last fill), then cooldown.
"""

from __future__ import annotations

from pandas import DataFrame

from GridAIBase import GridAIBase


class BTCAccumGridAI(GridAIBase):
    can_short = False

    # Selected on in-sample data only (2021-06-01 .. 2024-12-12); see references/backtest-results.md
    GRID = {
        **GridAIBase.GRID,
        "alloc": 0.95,
        "max_lots": 12,
        "core_frac": 0.60,  # BTC's drift pays: with the 100-day EMA, core 0.6 beat 0.3 in every cell
        "step_mult": 2.5,  # flat plateau 1.5-3.5
        "step_min": 0.007,
        "step_max": 0.035,
        "break_steps": 3.0,
        "trail_steps": 0.0,
        "cooldown_hours": 72,
        "trend_ema": 2400,  # ~100-day EMA: beat the 50-day in all 12 paired cells
        "ema_band": 0.03,
        "enter_z": -0.25,
        "add_z": -1.0,
        "exit_z": -0.5,
        "vr_max": 0.35,
    }

    def regime(self, df: DataFrame) -> DataFrame:
        p = self.p
        ok = df["do_predict"] == 1
        calm = df["vol_ratio_pred"] <= p["vr_max"]
        z = df["trend_z"]
        df["grid_long_on"] = ok & df["above"] & (z >= p["enter_z"])
        df["grid_long_add"] = ok & calm & (z >= p["add_z"])
        df["grid_long_off"] = df["below"] & (z <= p["exit_z"])
        return df
