"""MacdGatedFutures + FreqAI LightGBM gate (off unless macd_gates.ml_filter is true).

Labels follow agiprolabs signal-classification: forward return vs a ±threshold,
dropping the neutral band. Probability threshold is NOT hardcoded to 0.5;
default 0.65 is a placeholder in the documented 0.60–0.75 band and must be
re-optimized on walk-forward OOS (profit factor) before enabling this gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from MacdGatedFutures import MacdGatedFutures


class MacdGatedML(MacdGatedFutures):
    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.freqai_info = config.get("freqai", {})

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe[f"%-rsi-period_{period}"] = dataframe["close"].pct_change().rolling(period).std()
        dataframe[f"%-rel_vol-period_{period}"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        if "macd_delta" in dataframe.columns:
            dataframe[f"%-macd_delta-period_{period}"] = dataframe["macd_delta"]
        if "adx" in dataframe.columns:
            dataframe[f"%-adx-period_{period}"] = dataframe["adx"]
        return dataframe

    def feature_engineering_standard(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        dataframe["%-raw_close"] = dataframe["close"]
        dataframe["%-raw_volume"] = dataframe["volume"]
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        period = int(self.freqai_info.get("feature_parameters", {}).get("label_period_candles", 16))
        threshold = float(self._settings().get("ml_label_threshold", 0.01))
        fwd = dataframe["close"].shift(-period) / dataframe["close"] - 1
        labels = np.where(fwd > threshold, "up", np.where(fwd < -threshold, "down", None))
        self.freqai.class_names = ["down", "up"]
        dataframe["&s-direction"] = labels
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        if self.freqai_info.get("enabled"):
            dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs) -> bool:
        if not super().confirm_trade_entry(
            pair, order_type, amount, rate, time_in_force, current_time, entry_tag, side, **kwargs
        ):
            return False
        if not self._gate_on("ml_filter"):
            return True
        threshold = float(self._settings().get("ml_prob_threshold", 0.65))
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            return False
        if df is None or df.empty:
            return False
        last = df.iloc[-1]
        do_predict = last.get("do_predict", 0)
        if do_predict != 1:
            return False
        # Expected FreqAI classifier probability columns.
        if side == "long" or side == "buy":
            prob = last.get("up", last.get("&s-direction_up", last.get("do_predict", 0)))
            try:
                return float(prob) >= threshold
            except (TypeError, ValueError):
                return False
        prob = last.get("down", last.get("&s-direction_down", 0))
        try:
            return float(prob) >= threshold
        except (TypeError, ValueError):
            return False
