"""FuturesEABase: long + short trend-following EA for USDT-M perpetual futures (Freqtrade + FreqAI).

Long side   identical to EABase (the validated spot EAs): breakout above the slow trend EMA,
            chandelier stop from the highest price, exit when the trend ends or BTC turns risk-off.
Short side  the mirror image, with its own parameters (``s_*``, researched on the development
            period only): close breaks below the lowest low of the previous ``s_breakout_h`` hours
            while price is below the short trend EMA band (optionally with the EMA falling, and
            for ETH only while BTC is risk-off); chandelier stop from the lowest price since entry;
            exit when price closes back above the band ("trend_off") or BTC turns risk-on
            ("risk_on"). Optional bear-regime gate ``s_cross``: the faster EMA must be below the
            100-day EMA.
Size        fixed fractional risk as in EABase, per side: notional = equity x clip(risk /
            (trail_k x sigma_day), min_alloc, max_alloc). Leverage never enlarges the position.
Leverage    isolated margin; leverage = the largest integer that keeps the liquidation price at
            least ``liq_buffer`` x the initial stop distance away (max ``max_leverage``, min 1).
            It only reduces the margin the position ties up.
Stops       the price stop is capped at ``max_stop_pct`` from the entry (the spot EAs' -30% hard
            stop). Stops move only in the trade's favour and sit on the exchange in live trading.

The protocol is references/futures-validation-protocol.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import talib.abstract as ta
from EABase import EABase
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
from pandas import DataFrame


class FuturesEABase(EABase):
    can_short = True
    stoploss = -0.99  # the price cap lives in custom_stoploss (max_stop_pct), independent of leverage

    MMR = 0.01  # conservative maintenance margin rate for the liquidation buffer

    EA: dict[str, Any] = {
        **EABase.EA,
        "short": True,
        "s_trend_ema": None,  # None = same as the long side
        "s_ema_band": None,
        "s_slope_h": None,  # >0: EMA must be lower than s_slope_h hours ago to short
        "s_cross": 0,  # >0: bear regime only - EMA(s_cross) must be below EMA(2400) (a "death cross")
        "s_breakout_h": None,
        "s_init_k": None,
        "s_trail_k": None,
        "s_risk_per_trade": None,
        "max_stop_pct": 0.30,
        "max_leverage": 3,
        "liq_buffer": 2.0,
    }

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        p = self.p
        for k in ("trend_ema", "ema_band", "slope_h", "breakout_h", "trail_k", "risk_per_trade"):
            if p.get(f"s_{k}") is None:
                p[f"s_{k}"] = p[k]
        if p.get("s_init_k") is None:
            p["s_init_k"] = p["s_trail_k"]

    def ref_pair(self) -> str:
        stake = self.config["stake_currency"]
        return f"BTC/{stake}:{stake}" if self.config.get("trading_mode") == "futures" else f"BTC/{stake}"

    # ---------------------------------------------------------------- signals
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_indicators(dataframe, metadata)
        p = self.p
        if int(p["s_trend_ema"]) == int(p["trend_ema"]):
            ema = df["ema_slow"]
        else:
            ema = ta.EMA(df, timeperiod=int(p["s_trend_ema"]))
        df["ema_short"] = ema
        df["s_below"] = df["close"] < ema * (1 - p["s_ema_band"])
        df["s_above"] = df["close"] > ema * (1 + p["s_ema_band"])
        sh = int(p["s_slope_h"])
        df["falling"] = ema < ema.shift(sh) if sh > 0 else True
        df["donchian_low"] = df["low"].rolling(int(p["s_breakout_h"])).min().shift(1)
        cross = int(p.get("s_cross") or 0)
        if cross > 0:
            slow = df["ema_slow"] if int(p["trend_ema"]) == 2400 else ta.EMA(df, timeperiod=2400)
            fast = ema if int(p["s_trend_ema"]) == cross else ta.EMA(df, timeperiod=cross)
            df["bear"] = fast < slow
        else:
            df["bear"] = True
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        if not self.p["short"] or not self.can_short:
            return df
        ref_ok = df["risk_off"] if int(self.p["ref_trend_ema"]) > 0 else True
        go = (
            (df["do_predict"] == 1)
            & (df["close"] < df["donchian_low"])
            & df["s_below"]
            & df["falling"]
            & df["bear"]
            & ref_ok
            & (df["sigma_day"] > 0)
            & (df["volume"] > 0)
        )
        df.loc[go, ["enter_short", "enter_tag"]] = (1, "breakdown")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_exit_trend(dataframe, metadata)
        if not self.p["short"] or not self.can_short:
            return df
        df.loc[df["s_above"], ["exit_short", "exit_tag"]] = (1, "trend_off")
        if int(self.p["ref_trend_ema"]) > 0:
            df.loc[df["risk_on"] & ~df["s_above"], ["exit_short", "exit_tag"]] = (1, "risk_on")
        return df

    # ----------------------------------------------------------------- sizing
    def _side(self, short: bool) -> tuple[float, float, float]:
        p = self.p
        if short:
            return p["s_risk_per_trade"], p["s_trail_k"], p["s_init_k"]
        return p["risk_per_trade"], p["trail_k"], (p["trail_k"] if p["init_k"] is None else p["init_k"])

    def _stop_dist(self, sd: float, short: bool) -> float:
        _r, _k, init_k = self._side(short)
        return min(init_k * sd, self.p["max_stop_pct"])

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float,
                 max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        sd = (self._row(pair, current_time) or {}).get("sigma_day") or 0.0
        if not np.isfinite(sd) or sd <= 0:
            return 1.0
        d = self._stop_dist(sd, side == "short")
        lev = int(1.0 / (self.p["liq_buffer"] * d + self.MMR))
        return float(max(1, min(lev, int(self.p["max_leverage"]), int(max_leverage))))

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs) -> float:
        p = self.p
        sd = (self._row(pair, current_time) or {}).get("sigma_day") or 0.0
        if not np.isfinite(sd) or sd <= 0:
            return 0.0
        risk, trail_k, _ = self._side(side == "short")
        alloc = float(np.clip(risk / (trail_k * sd), p["min_alloc"], p["max_alloc"]))
        stake = self.wallets.get_total_stake_amount() * alloc / max(float(leverage or 1.0), 1.0)
        return float(max(min(stake, max_stake), min_stake or 0.0))

    # ------------------------------------------------------------------ stops
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float | None:
        sd = self._sigma_entry(trade)
        if sd is None or sd <= 0:
            return None
        _r, trail_k, init_k = self._side(trade.is_short)
        cap = self.p["max_stop_pct"]
        if trade.is_short:
            init = trade.open_rate * (1 + min(init_k * sd, cap))
            trail = (trade.min_rate or trade.open_rate) * (1 + trail_k * sd)
            stop = min(init, trail)
            if stop <= current_rate:
                return 0.0001  # price already through the stop: exit now
        else:
            init = trade.open_rate * (1 - min(init_k * sd, cap))
            trail = (trade.max_rate or trade.open_rate) * (1 - trail_k * sd)
            stop = max(init, trail)
            if stop >= current_rate:
                return 0.0001
        return stoploss_from_absolute(stop, current_rate, is_short=trade.is_short, leverage=trade.leverage)
