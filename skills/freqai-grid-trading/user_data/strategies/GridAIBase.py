"""GridAIBase: a FreqAI-steered trailing LIFO grid engine for Freqtrade.

Freqtrade holds one trade per pair, so the grid lives *inside* that trade:

* a grid "session" = one Freqtrade trade (long or short),
* every grid lot = one position-adjustment order (``adjust_trade_position``),
* every grid take-profit = one partial exit of exactly that lot's amount.

Mechanics (long side; the short side is mirrored):

* The session opens with an anchor (``core_frac`` of the allocation, or one lot when
  ``core_frac`` is 0). The anchor is only closed when the whole session ends.
* A new lot is bought when price falls one step below ``ref`` (the last fill price).
* The most recently bought lot (LIFO = the deepest one) is sold when price rises one step
  above *its own* buy price, so every grid round trip is closed at a profit of one step.
* With no grid lots open, ``ref`` trails price upwards, so the grid follows a rising market.
* Grid orders are resting limit orders at the exact grid level (``custom_entry_price`` /
  ``custom_exit_price``): the nearest one is placed once price is within ``rest_frac`` x
  step and fills only if price trades through the level (maker-style, like a real grid
  bot). Freqtrade allows one open order per trade, so only the nearest order rests;
  ``unfilledtimeout`` recycles it. Backtests therefore fill at the level, not at a better
  gap price (a fill audit showed the naive "trigger at candle open" model flattering
  BTC fills by ~16 bp each).

FreqAI (LightGBM, multi-target, purged walk-forward) predicts for every candle:

* ``&-vol_ratio`` log(forward / trailing 24h realised vol)
      -> sigma forecast -> grid step = ``step_mult`` x sigma (clipped);
      -> a predicted vol spike (> ``vr_max``) pauses new lots (grids bleed in breakouts).
* ``&-drift``     forward 72h smoothed drift in units of trailing volatility
      -> z-scored; a mild tilt for opening / adding / closing sessions. Direction is the
         weakest part of any forecast (walk-forward IC ~0.05), so it never acts alone:
         sessions also need the slow-EMA trend filter.

Session-level risk: a regime-off exit, a grid-break stop (price ``break_steps`` steps beyond
the last fill while the grid is full or FreqAI blocks new lots), an optional trailing profit
lock, and a cooldown after a stop. The grid ledger is reconciled with the real position on
every call (base-coin fees, partially filled orders).

Coin strategies subclass this and override ``GRID`` and ``regime()``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import talib.abstract as ta
from pandas import DataFrame

from freqtrade.persistence import Order, Trade
from freqtrade.strategy import IStrategy, merge_informative_pair, timeframe_to_prev_date


logger = logging.getLogger(__name__)

ROW_KEYS = (
    "grid_step",
    "sigma_pred",
    "grid_long_add",
    "grid_short_add",
    "trend_z",
    "do_predict",
)


def _finite(df: DataFrame) -> DataFrame:
    """Replace +-inf (log of zero volume / zero volatility in flat candles) by NaN.

    FreqAI drops NaN rows when training and flags them with do_predict=0 when predicting,
    but infinite values make LightGBM refuse the whole training window.
    """
    cols = [c for c in df.columns if c.startswith(("%", "&"))]
    df[cols] = df[cols].replace([np.inf, -np.inf], np.nan)
    return df


class GridAIBase(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 1300

    position_adjustment_enable = True
    max_entry_position_adjustment = -1

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    minimal_roi = {"0": 100.0}  # grid take-profits are handled lot by lot
    stoploss = -0.99  # session risk is handled by grid_break / regime_off / trail_lock
    trailing_stop = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    # Forward window (candles) of the volatility target.
    VOL_HORIZON = 24

    # Grid parameters. Subclasses override; config["grid_params"] overrides both.
    GRID: dict[str, Any] = {
        "alloc": 0.95,  # share of total wallet used by the session (margin, futures)
        "leverage": 1.0,  # futures only
        "max_lots": 10,  # grid lots on top of the anchor
        "core_frac": 0.0,  # share of the allocation held as anchor; 0 -> anchor = one lot
        "step_mult": 3.0,  # grid step = step_mult x predicted hourly sigma
        "step_min": 0.006,
        "step_max": 0.05,
        "break_steps": 3.0,  # stop: N steps beyond the last fill while full / adds blocked
        "trail_steps": 0.0,  # >0: lock profit when price retraces N steps from session best
        "cooldown_hours": 48,  # no new session after grid_break
        "trend_ema": 1200,  # slow regime EMA (1h candles, ~50 days)
        "ema_band": 0.0,  # hysteresis around the slow EMA (fraction of price)
        "enter_z": 0.0,  # FreqAI trend z-score needed to open a session
        "add_z": -1.0,  # trend z-score needed to keep adding lots
        "exit_z": -1.0,  # trend z-score that (together with the EMA filter) ends a session
        "vr_max": 0.35,  # pause new lots when FreqAI predicts vol to rise > e^0.35 (~+40%)
        "rest_frac": 0.5,  # rest the nearest grid order once price is within this x step
        "rel_ema": 0,  # >0: relative-strength filter, coin/BTC ratio vs its EMA (1h candles)
        "ref_trend_ema": 0,  # >0: BTC risk-on filter, BTC close vs its EMA (1h candles)
        "allow_short": True,  # futures strategies only (can_short = True)
        "ai_vol": True,  # False = ablation: naive trailing sigma instead of FreqAI, no vol pause
        "ai_drift": True,  # False = ablation: ignore FreqAI drift z (EMA filters only)
        "vol_target": 0.0,  # >0: daily vol target; session size x min(1, target / FreqAI sigma)
        "vol_floor": 0.25,  # never size a session below this share of alloc
    }

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # same strategy file runs on spot (long only) or futures (shorts possible)
        self.can_short = bool(self.can_short) and config.get("trading_mode") == "futures"
        self.p: dict[str, Any] = {**self.GRID, **config.get("grid_params", {})}
        if not self.p["ai_drift"]:  # ablation: every drift-z condition passes
            self.p.update(enter_z=-99.0, add_z=-99.0, exit_z=99.0)
        self._grid: dict[int, dict] = {}
        self._pending: dict[int, dict] = {}
        self._rows: dict[str, tuple] = {}
        self._cooldown_until: dict[str, datetime] = {}

    # ------------------------------------------------------------------ FreqAI
    # All features are scale-free (log returns, log-vol ratios, normalised distances), so a
    # model trained on one price/volatility regime still applies in the next one. A
    # walk-forward study showed this matters: raw-level features gave a volatility IC of
    # ~0.2-0.35, scale-free ones ~0.6 on the same data.
    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        # called for the traded pair and every corr pair, per period in
        # indicator_periods_candles; FreqAI appends the period / pair / tf suffixes
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

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        df = dataframe
        logc = np.log(df["close"])
        rv24 = logc.diff().rolling(24).std()
        df["%-ret1"] = logc.diff() / rv24
        df["%-hl"] = np.log((df["high"] - df["low"]) / df["close"] + 1e-9) - np.log(rv24)
        return _finite(df)

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        # traded pair only
        df = dataframe
        logc = np.log(df["close"])
        ret = logc.diff()
        rv168 = ret.rolling(168).std()
        for n in (50, 200, 800):
            df[f"%-dema{n}"] = (logc - np.log(ta.EMA(df, timeperiod=n))) / (rv168 * np.sqrt(n))
        df["%-lrv720"] = np.log(ret.rolling(720).std())  # absolute volatility level
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
        # forward / trailing realised volatility (log ratio): > 0 means vol expansion ahead
        df["&-vol_ratio"] = np.log(rv.shift(-hv) / rv)
        # forward smoothed drift in units of trailing volatility
        fwd = logc.rolling(horizon).mean().shift(-horizon) - logc
        df["&-drift"] = fwd / (ret.rolling(168).std() * np.sqrt(horizon))
        return _finite(df)

    # -------------------------------------------------------------- indicators
    def ref_pair(self) -> str:
        stake = self.config["stake_currency"]
        if self.config.get("trading_mode") == "futures":
            return f"BTC/{stake}:{stake}"
        return f"BTC/{stake}"

    def _uses_ref(self) -> bool:
        return int(self.p["rel_ema"]) > 0 or int(self.p["ref_trend_ema"]) > 0

    def informative_pairs(self):
        return [(self.ref_pair(), self.timeframe)] if self._uses_ref() else []

    def add_relative_strength(self, df: DataFrame) -> DataFrame:
        """BTC context for alt-coin grids (both default to True when switched off).

        lead     coin/BTC ratio above its slow EMA (the coin outperforms BTC)   [rel_ema]
        ref_up   BTC above its slow EMA x (1 + ema_band): crypto risk-on       [ref_trend_ema]
        ref_down BTC below its slow EMA x (1 - ema_band): crypto risk-off
        """
        # neutral defaults: entries pass, risk-off exits never fire
        df["lead"], df["ref_up"], df["ref_down"] = True, True, False
        if not self._uses_ref():
            return df
        ref = self.dp.get_pair_dataframe(self.ref_pair(), self.timeframe)[["date", "close"]]
        df = merge_informative_pair(df, ref, self.timeframe, self.timeframe, ffill=True)
        ref_close = df[f"close_{self.timeframe}"]
        if int(self.p["rel_ema"]) > 0:
            ratio = df["close"] / ref_close
            df["lead"] = ratio > ta.EMA(ratio, timeperiod=int(self.p["rel_ema"]))
        if int(self.p["ref_trend_ema"]) > 0:
            ref_ema = ta.EMA(ref_close, timeperiod=int(self.p["ref_trend_ema"]))
            band = float(self.p["ema_band"])
            df["ref_up"] = ref_close > ref_ema * (1 + band)
            df["ref_down"] = ref_close < ref_ema * (1 - band)
        return df.drop(columns=[f"close_{self.timeframe}", f"date_{self.timeframe}"])

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.add_relative_strength(dataframe)
        df = self.freqai.start(dataframe, metadata, self)
        p = self.p
        logc = np.log(df["close"])
        rv = logc.diff().rolling(self.VOL_HORIZON).std()
        df["ema_slow"] = ta.EMA(df, timeperiod=int(p["trend_ema"]))
        df["ema_slope"] = df["ema_slow"].pct_change(24)
        # hysteresis band around the slow EMA: open above (1+band), close below (1-band)
        df["above"] = df["close"] > df["ema_slow"] * (1 + p["ema_band"])
        df["below"] = df["close"] < df["ema_slow"] * (1 - p["ema_band"])
        # FreqAI outputs: predicted hourly sigma for the next day, vol-expansion and drift z
        df["vol_ratio_pred"] = df["&-vol_ratio"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        if not p["ai_vol"]:  # ablation: naive "tomorrow = today" volatility
            df["vol_ratio_pred"] = 0.0
        df["sigma_pred"] = rv * np.exp(df["vol_ratio_pred"])
        std = df["&-drift_std"].replace(0, np.nan)
        df["trend_z"] = ((df["&-drift"] - df["&-drift_mean"]) / std).fillna(0.0)
        df["grid_step"] = (p["step_mult"] * df["sigma_pred"]).clip(p["step_min"], p["step_max"])
        df["grid_step"] = df["grid_step"].fillna(p["step_max"])
        for col in (
            "grid_long_on",
            "grid_long_add",
            "grid_long_off",
            "grid_short_on",
            "grid_short_add",
            "grid_short_off",
        ):
            df[col] = False
        df = self.regime(df)
        return df

    def regime(self, df: DataFrame) -> DataFrame:
        """Default: long-only, slow EMA trend + FreqAI drift tilt + vol-spike pause."""
        p = self.p
        ok = df["do_predict"] == 1
        calm = df["vol_ratio_pred"] <= p["vr_max"]
        z = df["trend_z"]
        df["grid_long_on"] = ok & df["above"] & (z >= p["enter_z"])
        df["grid_long_add"] = ok & calm & (z >= p["add_z"])
        df["grid_long_off"] = df["below"] & (z <= p["exit_z"])
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[df["grid_long_on"], ["enter_long", "enter_tag"]] = (1, "grid_long")
        if self.can_short and self.p["allow_short"]:
            df.loc[df["grid_short_on"], ["enter_short", "enter_tag"]] = (1, "grid_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[df["grid_long_off"], ["exit_long", "exit_tag"]] = (1, "regime_off")
        if self.can_short:
            df.loc[df["grid_short_off"], ["exit_short", "exit_tag"]] = (1, "regime_off")
        return df

    # ----------------------------------------------------------------- helpers
    def _row(self, pair: str, current_time: datetime | None = None) -> dict | None:
        """Last closed candle's grid columns, cached once per candle."""
        live = self.dp.runmode.value in ("live", "dry_run")
        cached = self._rows.get(pair)
        if not live and current_time is not None and cached is not None:
            # backtesting: the analyzed frame only changes when a new main candle starts
            if cached[2] == timeframe_to_prev_date(self.timeframe, current_time):
                return cached[1]
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        key = df["date"].iat[-1]
        if cached is not None and cached[0] == key:
            row = cached[1]
        else:
            last = df.iloc[-1]
            row = {k: last[k] for k in ROW_KEYS if k in last.index}
        bucket = timeframe_to_prev_date(self.timeframe, current_time) if current_time else None
        self._rows[pair] = (key, row, bucket)
        return row

    def _state(self, trade: Trade) -> dict | None:
        st = self._grid.get(trade.id)
        if st is None:
            st = trade.get_custom_data("grid")
            if st is not None:
                self._grid[trade.id] = st
        return st

    def _save(self, trade: Trade, st: dict | None) -> None:
        if st is None:
            self._grid.pop(trade.id, None)
        else:
            self._grid[trade.id] = st
        if self.dp.runmode.value in ("live", "dry_run"):
            trade.set_custom_data("grid", st)

    def _reconcile(self, trade: Trade, st: dict) -> bool:
        """Keep the grid ledger equal to the real position.

        Live spot fees charged in the base coin, or an order that was partially filled and
        then cancelled, make trade.amount differ from anchor + lots. A surplus goes to the
        anchor; a shortfall is taken from the anchor first, then from the newest lots.
        Backtests never trigger this (amounts match to float precision).
        """
        held = st["anchor"] + sum(lot[1] for lot in st["lots"])
        diff = float(trade.amount) - held
        if abs(diff) <= 1e-6 * max(abs(float(trade.amount)), 1e-12):
            return False
        if diff > 0:
            st["anchor"] += diff
            return True
        short = -diff
        take = min(short, st["anchor"])
        st["anchor"] -= take
        short -= take
        while short > 0 and st["lots"]:
            lot = st["lots"][-1]
            if lot[1] <= short:
                short -= lot[1]
                st["lots"].pop()
            else:
                lot[1] -= short
                short = 0.0
        return True

    def _anchor_share(self) -> float:
        cf = float(self.p["core_frac"])
        if cf <= 0:
            return 1.0
        lot = (1 - cf) / int(self.p["max_lots"])
        return cf / (cf + lot)

    # ---------------------------------------------------------------- sizing
    def leverage(self, pair, current_time, current_rate, proposed_leverage, max_leverage,
                 entry_tag, side, **kwargs) -> float:
        return float(min(self.p["leverage"], max_leverage))

    def session_alloc(self, pair: str, current_time: datetime) -> float:
        """Share of the wallet for a new session: alloc, scaled down by FreqAI's vol forecast.

        Volatility targeting: size = alloc x min(1, vol_target / predicted daily sigma),
        floored at vol_floor x alloc. Uses the part of the forecast that has real skill.
        """
        p = self.p
        alloc = float(p["alloc"])
        target = float(p["vol_target"])
        if target <= 0:
            return alloc
        row = self._row(pair, current_time) or {}
        sigma = float(row.get("sigma_pred") or 0.0) * np.sqrt(24)
        if not np.isfinite(sigma) or sigma <= 0:
            return alloc * float(p["vol_floor"])
        return alloc * float(np.clip(target / sigma, float(p["vol_floor"]), 1.0))

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs) -> float:
        p = self.p
        alloc = self.wallets.get_total_stake_amount() * self.session_alloc(pair, current_time)
        core = alloc * float(p["core_frac"])
        if core > 0:  # core + first lot now, max_lots - 1 more lots later
            stake = core + (alloc - core) / int(p["max_lots"])
        else:  # anchor is one lot: max_lots + 1 lots in total
            stake = alloc / (int(p["max_lots"]) + 1)
        return float(max(min(stake, max_stake), min_stake or 0.0))

    # ------------------------------------------------------------------- grid
    def adjust_trade_position(self, trade: Trade, current_time: datetime, current_rate: float,
                              current_profit: float, min_stake: float | None, max_stake: float,
                              current_entry_rate: float, current_exit_rate: float,
                              current_entry_profit: float, current_exit_profit: float,
                              **kwargs) -> float | None | tuple[float | None, str | None]:
        if trade.has_open_orders:
            return None
        st = self._state(trade)
        row = self._row(trade.pair, current_time)
        if st is None or row is None:
            return None
        d = -1 if trade.is_short else 1
        price = current_rate
        dirty = self._reconcile(trade, st)
        lots = st["lots"]

        # session best price (for the optional trailing profit lock)
        if d * (price - st["best"]) > 0:
            st["best"] = price
            dirty = True

        step = float(row["grid_step"])
        # 1) trail the reference when only the anchor is left
        if not lots and d * (price - st["ref"] * (1 + d * step)) > 0:
            st["ref"] = price
            dirty = True
        if dirty:
            self._save(trade, st)

        # 2) candidate orders: take profit on the deepest lot (LIFO) / add one lot
        #    one step beyond the reference. Only the nearest one rests on the book.
        window = float(self.p["rest_frac"]) * step
        cands = []
        if lots:
            _, amount, target = lots[-1]
            cands.append((d * (target - price) / price, "grid_sell", target, amount))
        add_ok = bool(row["grid_long_add"] if d == 1 else row["grid_short_add"])
        if add_ok and len(lots) < int(self.p["max_lots"]):
            level = st["ref"] * (1 - d * step)
            cands.append((d * (price - level) / price, "grid_buy", level, None))
        if not cands:
            return None
        dist, tag, level, amount = min(cands, key=lambda c: c[0])
        if dist > window:  # still far away: do not park a stale order
            return None
        if tag == "grid_sell":
            stake = amount * trade.stake_amount / trade.amount
            self._pending[trade.id] = {"price": level}
            return -stake, "grid_sell"
        stake = min(st["lot_stake"], max_stake)
        if stake <= 0 or (min_stake and stake < min_stake):
            return None
        self._pending[trade.id] = {"price": level, "step": step}
        return stake, "grid_buy"

    def custom_entry_price(self, pair: str, trade: Trade | None, current_time: datetime,
                           proposed_rate: float, entry_tag: str | None, side: str,
                           **kwargs) -> float:
        # Fill grid lots at the grid level (never at a better gap price).
        if trade is not None and entry_tag == "grid_buy":
            pend = self._pending.get(trade.id)
            if pend:
                return pend["price"]
        return proposed_rate

    def custom_exit_price(self, pair: str, trade: Trade, current_time: datetime,
                          proposed_rate: float, current_profit: float, exit_tag: str | None,
                          **kwargs) -> float:
        if exit_tag == "grid_sell":
            pend = self._pending.get(trade.id)
            if pend:
                return pend["price"]
        return proposed_rate

    def order_filled(self, pair: str, trade: Trade, order: Order, current_time: datetime,
                     **kwargs) -> None:
        price = float(order.safe_price)
        amount = float(order.safe_filled)
        if amount <= 0:
            return
        d = -1 if trade.is_short else 1
        st = self._state(trade)
        pend = self._pending.pop(trade.id, None) or {}
        if order.ft_order_side == trade.entry_side:
            if st is None:  # session start: anchor (+ first lot when core_frac > 0)
                share = self._anchor_share()
                anchor = amount * share
                stake = amount * price / trade.leverage
                lot_stake = stake * (1 - share) if share < 1 else stake
                st = {
                    "anchor": anchor,
                    "lots": [],
                    "ref": price,
                    "best": price,
                    "lot_stake": lot_stake,
                    "buys": 0,
                    "sells": 0,
                }
                if share < 1:
                    row = self._row(pair) or {}
                    step = float(row.get("grid_step", self.p["step_min"]))
                    st["lots"].append([price, amount - anchor, price * (1 + d * step)])
            else:
                step = float(pend.get("step", self.p["step_min"]))
                st["lots"].append([price, amount, price * (1 + d * step)])
                st["buys"] += 1
            st["ref"] = price
            self._save(trade, st)
        elif st is not None and order.ft_order_tag == "grid_sell":
            remaining = amount
            while st["lots"] and remaining > 1e-12:
                lot = st["lots"][-1]
                if lot[1] <= remaining * (1 + 1e-6):
                    remaining -= lot[1]
                    st["lots"].pop()
                else:
                    lot[1] -= remaining
                    remaining = 0.0
            st["ref"] = price
            st["sells"] += 1
            self._save(trade, st)
        elif not trade.is_open or order.ft_order_tag != "grid_sell":
            self._save(trade, None)

    # ------------------------------------------------------------ session exit
    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs) -> str | None:
        st = self._state(trade)
        row = self._row(pair, current_time)
        if st is None or row is None:
            return None
        d = -1 if trade.is_short else 1
        step = float(row["grid_step"])
        # Grid break: the grid can no longer absorb the move (full, or FreqAI blocks new
        # lots) and price is break_steps beyond the last fill -> close the whole session.
        full = len(st["lots"]) >= int(self.p["max_lots"])
        blocked = not bool(row["grid_long_add"] if d == 1 else row["grid_short_add"])
        if full or blocked:
            if d * (st["ref"] * (1 - d * self.p["break_steps"] * step) - current_rate) > 0:
                return "grid_break"
        trail = float(self.p["trail_steps"])
        if trail > 0 and current_profit > 0:
            if d * (st["best"] * (1 - d * trail * step) - current_rate) > 0:
                return "trail_lock"
        return None

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        if exit_reason == "grid_break":
            hours = float(self.p["cooldown_hours"])
            self._cooldown_until[pair] = current_time + timedelta(hours=hours)
        return True

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None,
                            side: str, **kwargs) -> bool:
        until = self._cooldown_until.get(pair)
        return until is None or current_time >= until
