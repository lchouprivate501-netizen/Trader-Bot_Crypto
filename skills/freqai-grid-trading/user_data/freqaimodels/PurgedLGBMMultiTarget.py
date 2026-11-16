"""LightGBM multi-target regressor with a purged training tail.

FreqAI computes targets on the whole dataframe and only then slices out each walk-forward
training window. Targets that look H candles ahead therefore leak up to H candles of the
*following* (test) window into the last H training rows. This model drops those rows before
fitting, so backtests see exactly what a live bot would see: in live/dry-run the last H rows
have no label yet and are discarded anyway, so the behaviour is identical there.

Purge length = freqai.feature_parameters.label_period_candles (the longest target horizon).
"""

from __future__ import annotations

import logging
from typing import Any

from pandas import DataFrame

from freqtrade.freqai.data_kitchen import FreqaiDataKitchen
from freqtrade.freqai.prediction_models.LightGBMRegressorMultiTarget import (
    LightGBMRegressorMultiTarget,
)


logger = logging.getLogger(__name__)


class PurgedLGBMMultiTarget(LightGBMRegressorMultiTarget):
    def train(self, unfiltered_df: DataFrame, pair: str, dk: FreqaiDataKitchen, **kwargs) -> Any:
        purge = int(self.freqai_info.get("feature_parameters", {}).get("label_period_candles", 0))
        if not self.live and purge > 0 and len(unfiltered_df) > purge * 4:
            unfiltered_df = unfiltered_df.iloc[:-purge]
            logger.info(f"{pair}: purged last {purge} candles of the training window (label horizon)")
        return super().train(unfiltered_df, pair, dk, **kwargs)
