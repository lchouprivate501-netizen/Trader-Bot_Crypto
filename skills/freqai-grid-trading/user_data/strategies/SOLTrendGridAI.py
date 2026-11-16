"""SOLTrendGridAI - SOL trend-aligned wide grid steered by FreqAI (spot, long-only by default).

Why this shape for SOL
* By far the most volatile of the three (annualised 80-170%), with strong momentum regimes
  (2021 +9000%, 2023-24 +2000%) and violent crashes (2022 -96%). A tight, neutral grid gets
  run over; a grid that only trades *with* a confirmed trend and harvests the pullbacks
  inside it fits SOL's personality.
* Faster trend filter than BTC (50-day EMA that must also be rising): SOL's trends start and
  end abruptly; in-sample the 100-day EMA was worse in most paired tests.
* Honest status: the weakest of the three (full-period drawdown ~48%, out-of-sample loss);
  see references/backtest-results.md before allocating real money.
* Wide steps (bigger sigma multiple, higher floor) keep fees small relative to each step,
  few lots keep inventory small, and a trailing profit lock (trail_steps x step from the
  session's best price) banks trend runs before the inevitable crash. (In the perp variants
  trail-lock exits were the biggest profit source; in the final spot run most sessions end
  on grid_break instead - see references/backtest-results.md.)
* BTC and ETH lead SOL: both are in the FreqAI feature set (include_corr_pairlist).
* Spot by default. The short side (futures + allow_short) is kept in the code but lost
  money in every in-sample variant we tested (shorts into SOL's 2023 rally), and a long
  perp position pays funding, so long-only spot is the default.

Logic
* Session: price above the rising slow EMA and FreqAI drift z >= enter_z.
  Lots only while FreqAI does not predict a volatility spike and drift z >= add_z.
* Exit: trail_lock, regime_off (below the EMA and bearish z), grid_break, then cooldown.
"""

from __future__ import annotations

from pandas import DataFrame

from GridAIBase import GridAIBase


class SOLTrendGridAI(GridAIBase):
    can_short = True

    # Selected on in-sample data only (2021-06-01 .. 2024-12-12); see references/backtest-results.md
    GRID = {
        **GridAIBase.GRID,
        "alloc": 0.95,
        "max_lots": 6,
        "core_frac": 0.30,
        "step_mult": 2.0,
        "step_min": 0.015,
        "step_max": 0.08,
        "break_steps": 3.0,
        # Tested and NOT adopted (references/tradingview-research.md): full_break_steps 6 +
        # step_growth 0.5 lifted in-sample Calmar 0.78 -> 2.02 but out-of-sample got worse.
        "full_break_steps": None,
        "step_growth": 0.0,
        "trail_steps": 6.0,
        "cooldown_hours": 72,
        "trend_ema": 1200,  # ~50 days: beat ~100 days in-sample for SOL
        "rel_ema": 0,
        "allow_short": False,  # futures only; lost money in-sample, off
        "enter_z": 0.25,
        "add_z": 0.0,
        "exit_z": -0.25,
    }

    def regime(self, df: DataFrame) -> DataFrame:
        p = self.p
        ok = df["do_predict"] == 1
        calm = df["vol_ratio_pred"] <= p["vr_max"]
        rising = df["ema_slope"] > 0
        z = df["trend_z"]
        lead = df["lead"]  # SOL/BTC above its slow EMA (always True when rel_ema = 0)
        df["grid_long_on"] = ok & df["above"] & rising & lead & (z >= p["enter_z"])
        df["grid_long_add"] = ok & calm & (z >= p["add_z"])
        df["grid_long_off"] = df["below"] & (z <= p["exit_z"])
        weak = ~lead if int(p["rel_ema"]) > 0 else True
        df["grid_short_on"] = ok & df["below"] & ~rising & weak & (z <= -p["enter_z"])
        df["grid_short_add"] = ok & calm & (z <= -p["add_z"])
        df["grid_short_off"] = df["above"] & (z >= -p["exit_z"])
        df["grid_long_on"] &= ~df["grid_long_off"]
        df["grid_short_on"] &= ~df["grid_short_off"]
        return df
