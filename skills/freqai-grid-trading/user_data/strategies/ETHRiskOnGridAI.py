"""ETHRiskOnGridAI - ETH spot grid that only runs in BTC "risk-on" regimes, steered by FreqAI.

Why this shape for ETH
* ETH is high-beta BTC: ~1.2-1.3x BTC's volatility and correlation ~0.8+, but with deep,
  long bear legs of its own (2022 -68%, 2024-25 -60%) and a multi-year downtrend against
  BTC. A plain ETH grid keeps buying those falling knives.
* ETH's good periods coincide with crypto-wide risk-on phases. So the session filter is
  two-level: ETH above its own ~50-day EMA *and* BTC above its ~100-day EMA. In-sample this
  BTC filter was the one robust ETH-specific edge: all 12 tested variants with it were
  profitable (Calmar 0.31-0.60), without it half of them lost money (best 0.42).
* What did NOT work for ETH (in-sample, documented in references/backtest-results.md):
  a bidirectional long/short perp grid, an ETH/BTC relative-strength filter, and
  volatility-targeted sizing. Shorts are still available on futures (allow_short) but off.
* A 40% core rides ETH's trend inside risk-on phases; the grid harvests its larger swings.
* BTC is in the FreqAI feature set (include_corr_pairlist).

Logic
* Session: ETH above its EMA, BTC above its EMA (ref_trend_ema), FreqAI drift z >= enter_z.
* Lots only while FreqAI does not predict a volatility spike and drift z >= add_z.
* Exit: regime_off (ETH below its EMA or BTC risk-off, and bearish z), grid_break, cooldown.
"""

from __future__ import annotations

from pandas import DataFrame

from GridAIBase import GridAIBase


class ETHRiskOnGridAI(GridAIBase):
    can_short = True

    # Selected on in-sample data only (2021-06-01 .. 2024-12-12); see references/backtest-results.md
    GRID = {
        **GridAIBase.GRID,
        "alloc": 0.95,
        "max_lots": 10,
        "core_frac": 0.40,
        "step_mult": 2.5,
        "step_min": 0.008,
        "step_max": 0.045,
        "break_steps": 2.5,
        "trail_steps": 0.0,
        "cooldown_hours": 48,
        "trend_ema": 1200,  # ETH's own trend, ~50 days
        "ref_trend_ema": 2400,  # BTC risk-on filter, ~100 days
        "rel_ema": 0,  # ETH/BTC relative strength: hurt in-sample, off
        "allow_short": False,  # futures only; lost money in-sample, off
        "enter_z": 0.0,
        "add_z": -0.75,
        "exit_z": -0.25,
    }

    def regime(self, df: DataFrame) -> DataFrame:
        p = self.p
        ok = df["do_predict"] == 1
        calm = df["vol_ratio_pred"] <= p["vr_max"]
        z = df["trend_z"]
        lead = df["lead"]  # ETH/BTC above its slow EMA (True when rel_ema = 0)
        risk_on, risk_off = df["ref_up"], df["ref_down"]  # BTC trend (neutral when off)
        df["grid_long_on"] = ok & df["above"] & risk_on & lead & (z >= p["enter_z"])
        df["grid_long_add"] = ok & calm & (z >= p["add_z"])
        df["grid_long_off"] = (df["below"] | risk_off) & (z <= p["exit_z"])
        # short side (futures + allow_short only; off by default - it lost money in-sample)
        weak = ~lead if int(p["rel_ema"]) > 0 else True
        df["grid_short_on"] = ok & df["below"] & weak & (z <= -p["enter_z"])
        if int(p["ref_trend_ema"]) > 0:
            df["grid_short_on"] &= risk_off
        df["grid_short_add"] = ok & calm & (z <= -p["add_z"])
        df["grid_short_off"] = df["above"] & (z >= -p["exit_z"])
        df["grid_long_on"] &= ~df["grid_long_off"]
        df["grid_short_on"] &= ~df["grid_short_off"]
        return df
