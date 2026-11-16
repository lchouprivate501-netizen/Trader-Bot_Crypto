"""EABase: a trend-following Expert Advisor (EA) engine for Freqtrade + FreqAI.

One position per coin, spot, long only. Every decision is mechanical, so Freqtrade can run it
unattended (dry-run or live) with the stop held on the exchange.

Entry   close breaks above the highest high of the previous ``breakout_h`` hours, while
        price is above the slow trend EMA (with optional rising-slope and BTC risk-on gates)
        and FreqAI is not flagging the candle as an outlier.
Size    fixed fractional risk: stake = equity x clip(risk_per_trade / (trail_k x sigma_day),
        min_alloc, max_alloc). trail_k x sigma_day is the stop distance, so a stop-out costs
        about risk_per_trade of equity whatever the coin's volatility. sigma_day is FreqAI's
        forecast of the next day's volatility (smoothed over 72h).
Stop    chandelier stop from the highest price since entry: max(entry x (1 - init_k x s),
        highest x (1 - trail_k x s)), s = sigma_day frozen at entry. The stop only moves up
        and is placed on the exchange (stoploss_on_exchange) in live trading.
Exit    the stop, or the trend ending (close below the EMA band) or BTC turning risk-off.

FreqAI (LightGBM, purged walk-forward, retrained every 30 days) predicts the forward/trailing
volatility ratio; the drift target is trained too but not used for decisions (its
out-of-sample skill was ~0 in the grid research). ``ai_vol: False`` swaps in the naive
trailing volatility for ablation tests.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import (
    IStrategy,
    merge_informative_pair,
    stoploss_from_absolute,
    timeframe_to_prev_date,
)


logger = logging.getLogger(__name__)


def _finite(df: DataFrame) -> DataFrame:
    cols = [c for c in df.columns if c.startswith(("%", "&"))]
    df[cols] = df[cols].replace([np.inf, -np.inf], np.nan)
    return df


class EABase(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 2400

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    minimal_roi = {"0": 100.0}
    stoploss = -0.30  # hard cap; the chandelier stop is always tighter
    use_custom_stoploss = True
    trailing_stop = False
    position_adjustment_enable = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
    }

    VOL_HORIZON = 24

    # EA parameters. Coin EAs override; config["ea_params"] overrides both.
    EA: dict[str, Any] = {
        "trend_ema": 2400,  # slow trend EMA in 1h candles (2400 ~ 100 days)
        "ema_band": 0.0,  # hysteresis: enter above EMA x (1+band), exit below EMA x (1-band)
        "slope_h": 0,  # >0: EMA must be higher than slope_h hours ago to enter
        "breakout_h": 480,  # entry breakout lookback in hours (480 = 20 days)
        "init_k": None,  # initial stop: entry - init_k x daily sigma (None = trail_k)
        "trail_k": 3.0,  # chandelier stop: highest - trail_k x daily sigma
        "risk_per_trade": 0.05,  # equity lost if the stop is hit from the entry price
        "max_alloc": 0.95,
        "min_alloc": 0.05,
        "ref_trend_ema": 0,  # >0: BTC must be above its EMA (BTC risk-on gate)
        "ai_vol": True,  # False = ablation: naive trailing volatility instead of FreqAI
    }

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.p: dict[str, Any] = {**self.EA, **config.get("ea_params", {})}
        self._sd: dict[int, float] = {}
        self._rows: dict[str, tuple] = {}

    # ------------------------------------------------------------------ FreqAI
    # Same scale-free feature set and targets as the freqai-grid-trading skill.
    def feature_engineering_expand_all(self, dataframe: DataFrame, period: int, metadata: dict,
                                       **kwargs) -> DataFrame:
        df = dataframe
        logc = np.log(df["close"])
        ret = logc.diff()
        rv = ret.rolling(period).std()
        df["%-ret"] = (logc - logc.shift(period)) / (rv * np.sqrt(period))
        df["%-lrvrel"] = np.log(rv) - np.log(ret.rolling(720).std())
        df["%-er"] = (logc - logc.shift(period)).abs() / ret.abs().rolling(period).sum()
        hh = df["high"].rolling(period).max()
        ll = df["low"].rolling(period).min()
        df["%-rpos"] = (df["close"] - ll) / (hh - ll)
        df["%-rwidth"] = np.log((hh - ll) / df["close"]) - np.log(rv * np.sqrt(period))
        dollar = np.log(df["volume"] * df["close"] + 1.0)
        df["%-volz"] = dollar - dollar.rolling(period).mean()
        return _finite(df)

    def feature_engineering_expand_basic(self, dataframe: DataFrame, metadata: dict,
                                         **kwargs) -> DataFrame:
        df = dataframe
        logc = np.log(df["close"])
        rv24 = logc.diff().rolling(24).std()
        df["%-ret1"] = logc.diff() / rv24
        df["%-hl"] = np.log((df["high"] - df["low"]) / df["close"] + 1e-9) - np.log(rv24)
        return _finite(df)

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict,
                                     **kwargs) -> DataFrame:
        df = dataframe
        logc = np.log(df["close"])
        ret = logc.diff()
        rv168 = ret.rolling(168).std()
        for n in (50, 200, 800):
            df[f"%-dema{n}"] = (logc - np.log(ta.EMA(df, timeperiod=n))) / (rv168 * np.sqrt(n))
        df["%-lrv720"] = np.log(ret.rolling(720).std())
        df["%-vr6_72"] = np.log(ret.rolling(6).std()) - np.log(ret.rolling(72).std())
        df["%-day_of_week"] = df["date"].dt.dayofweek
        df["%-hour_of_day"] = df["date"].dt.hour
        return _finite(df)

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        df = dataframe
        horizon = int(self.freqai_info["feature_parameters"]["label_period_candles"])
        hv = min(self.VOL_HORIZON, horizon)
        logc = np.log(df["close"])
        ret = logc.diff()
        rv = ret.rolling(hv).std()
        df["&-vol_ratio"] = np.log(rv.shift(-hv) / rv)
        fwd = logc.rolling(horizon).mean().shift(-horizon) - logc
        df["&-drift"] = fwd / (ret.rolling(168).std() * np.sqrt(horizon))
        return _finite(df)

    # ---------------------------------------------------------------- context
    def ref_pair(self) -> str:
        stake = self.config["stake_currency"]
        return f"BTC/{stake}"

    def informative_pairs(self):
        return [(self.ref_pair(), self.timeframe)] if int(self.p["ref_trend_ema"]) > 0 else []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        p = self.p
        df = dataframe
        df["risk_on"], df["risk_off"] = True, False
        if int(p["ref_trend_ema"]) > 0:
            ref = self.dp.get_pair_dataframe(self.ref_pair(), self.timeframe)[["date", "close"]]
            df = merge_informative_pair(df, ref, self.timeframe, self.timeframe, ffill=True)
            rc = df[f"close_{self.timeframe}"]
            rema = ta.EMA(rc, timeperiod=int(p["ref_trend_ema"]))
            df["risk_on"] = rc > rema * (1 + p["ema_band"])
            df["risk_off"] = rc < rema * (1 - p["ema_band"])
            df = df.drop(columns=[f"close_{self.timeframe}", f"date_{self.timeframe}"])

        df = self.freqai.start(df, metadata, self)

        logc = np.log(df["close"])
        rv = logc.diff().rolling(self.VOL_HORIZON).std()
        ratio = df["&-vol_ratio"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if not p["ai_vol"]:
            ratio = ratio * 0.0
        df["sigma_pred"] = rv * np.exp(ratio)  # hourly, as in the grid skill
        df["sigma_day"] = (df["sigma_pred"] * np.sqrt(24)).ewm(span=72, adjust=False).mean()

        df["ema_slow"] = ta.EMA(df, timeperiod=int(p["trend_ema"]))
        df["above"] = df["close"] > df["ema_slow"] * (1 + p["ema_band"])
        df["below"] = df["close"] < df["ema_slow"] * (1 - p["ema_band"])
        slope_h = int(p["slope_h"])
        df["rising"] = df["ema_slow"] > df["ema_slow"].shift(slope_h) if slope_h > 0 else True
        df["donchian_high"] = df["high"].rolling(int(p["breakout_h"])).max().shift(1)
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        go = (
            (df["do_predict"] == 1)
            & (df["close"] > df["donchian_high"])
            & df["above"]
            & df["rising"]
            & df["risk_on"]
            & (df["sigma_day"] > 0)
            & (df["volume"] > 0)
        )
        df.loc[go, ["enter_long", "enter_tag"]] = (1, "breakout")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[df["below"], ["exit_long", "exit_tag"]] = (1, "trend_off")
        df.loc[df["risk_off"] & ~df["below"], ["exit_long", "exit_tag"]] = (1, "risk_off")
        return df

    # ----------------------------------------------------------------- helpers
    def _row(self, pair: str, current_time: datetime | None = None) -> dict | None:
        live = self.dp.runmode.value in ("live", "dry_run")
        cached = self._rows.get(pair)
        if not live and current_time is not None and cached is not None:
            if cached[1] == timeframe_to_prev_date(self.timeframe, current_time):
                return cached[0]
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        row = {"sigma_day": float(df["sigma_day"].iat[-1])}
        bucket = timeframe_to_prev_date(self.timeframe, current_time) if current_time else None
        self._rows[pair] = (row, bucket)
        return row

    def _sigma_entry(self, trade: Trade) -> float | None:
        sd = self._sd.get(trade.id)
        if sd is None:
            sd = trade.get_custom_data("sigma_day")
            if sd is not None:
                self._sd[trade.id] = float(sd)
        return sd

    # ------------------------------------------------------------- callbacks
    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs) -> float:
        p = self.p
        row = self._row(pair, current_time) or {}
        sd = row.get("sigma_day") or 0.0
        if not np.isfinite(sd) or sd <= 0:
            return 0.0
        alloc = float(np.clip(p["risk_per_trade"] / (p["trail_k"] * sd), p["min_alloc"], p["max_alloc"]))
        stake = self.wallets.get_total_stake_amount() * alloc
        return float(max(min(stake, max_stake), min_stake or 0.0))

    def order_filled(self, pair: str, trade: Trade, order: Order, current_time: datetime,
                     **kwargs) -> None:
        if order.ft_order_side == trade.entry_side and self._sigma_entry(trade) is None:
            row = self._row(pair) or {}
            sd = float(row.get("sigma_day") or 0.03)
            self._sd[trade.id] = sd
            if self.dp.runmode.value in ("live", "dry_run"):
                trade.set_custom_data("sigma_day", sd)

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                        current_profit: float, after_fill: bool, **kwargs) -> float | None:
        sd = self._sigma_entry(trade)
        if sd is None or sd <= 0:
            return None
        p = self.p
        init_k = p["trail_k"] if p["init_k"] is None else p["init_k"]
        init = trade.open_rate * (1 - init_k * sd)
        trail = (trade.max_rate or trade.open_rate) * (1 - p["trail_k"] * sd)
        stop = max(init, trail)
        if stop >= current_rate:
            return 0.0001  # price already through the stop: exit now
        return stoploss_from_absolute(stop, current_rate, is_short=False, leverage=trade.leverage)
