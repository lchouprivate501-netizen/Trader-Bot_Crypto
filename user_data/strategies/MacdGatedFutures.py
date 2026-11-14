"""MACD(12,26,9) delta-cross futures strategy with entry gates.

Entry: delta (= MACD - signal) crosses above 0 → long; below 0 → short.
Exit: opposite cross, never gated. Freqtrade is signals / dry_run only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair

import macd_gated_lib as lib

logger = logging.getLogger(__name__)

# Transitional ADX (20–25): ALLOW entries.
# regime-detection marks this band as "transitional", not "no trade".
# "Flatten on regime transition" in that skill refers to a quadrant change,
# not this ADX band. We log regime=transitional_allowed.
TRANSITIONAL_POLICY = "allow"


class MacdGatedFutures(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "15m"
    startup_candle_count = 1200
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    minimal_roi = {"0": 100}
    stoploss = -0.99
    trailing_stop = False
    use_custom_stoploss = False

    informative_timeframe = "1h"

    def version(self) -> str:
        return "1.1.0-macd-gated"

    def bot_start(self, **kwargs) -> None:
        g = self._gates()
        enabled = [k for k, v in g.items() if v and k != "log_signals"]
        logger.info(
            "MacdGatedFutures timeframe=%s startup_candle_count=%s informative=%s+1d "
            "daily_vol_source=datadir+informative_1d warmup=prev_completed_day_only "
            "gates_on=%s dry_run=%s",
            self.timeframe,
            self.startup_candle_count,
            self.informative_timeframe,
            ",".join(enabled) or "(none)",
            self.config.get("dry_run"),
        )

    def _gates(self) -> dict[str, Any]:
        return dict(self.config.get("macd_gates") or {})

    def _settings(self) -> dict[str, Any]:
        return dict(self.config.get("macd_gate_settings") or {})

    def _gate_on(self, name: str) -> bool:
        return bool(self._gates().get(name, False))

    def _journal_path(self) -> Path:
        rel = self._settings().get("journal_path", "logs/macd_gate_journal.jsonl")
        return Path(self.config["user_data_dir"]) / rel

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        return 1.0

    def informative_pairs(self) -> list[tuple[str, str]]:
        btc = self._settings().get("btc_pair", "BTC/USDT:USDT")
        pairs = [(btc, self.informative_timeframe), (btc, "1d")]
        for p in self.dp.current_whitelist():
            pairs.append((p, self.informative_timeframe))
            pairs.append((p, "1d"))
        return list(set(pairs))

    def _datadir(self) -> Path | None:
        raw = self.config.get("datadir")
        if raw:
            return Path(str(raw))
        ud = self.config.get("user_data_dir")
        if ud:
            return Path(str(ud)) / "data" / "okx"
        return None

    def _daily_close_for_vol(self, pair: str, dataframe: DataFrame) -> pd.Series:
        dp_daily = None
        try:
            dp_daily = self.dp.get_pair_dataframe(pair=pair, timeframe="1d")
        except Exception as exc:
            logger.debug("no live 1d dataframe for %s: %s", pair, exc)
        return lib.load_completed_daily_closes(
            pair=pair,
            dates_15m=dataframe["date"],
            close_15m=dataframe["close"],
            datadir=self._datadir(),
            dp_daily=dp_daily,
            trading_mode=str(self.config.get("trading_mode") or "futures"),
        )

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        s = self._settings()
        macd = lib.macd_delta(dataframe["close"], 12, 26, 9)
        dataframe = pd.concat([dataframe, macd], axis=1)
        dataframe["adx"] = lib.adx_skill(
            dataframe["high"], dataframe["low"], dataframe["close"], int(s.get("adx_period", 14))
        )
        dataframe["buy_vol_pct"] = lib.close_location_buy_pct(
            dataframe["high"], dataframe["low"], dataframe["close"]
        )
        dataframe["vol_anomaly"] = lib.volume_anomaly(
            dataframe["volume"],
            int(s.get("pressure_volume_lookback_bars", 96)),
            float(s.get("pressure_volume_anomaly_mult", 3.0)),
        )
        struct = lib.structure_flags(
            dataframe["high"],
            dataframe["low"],
            dataframe["close"],
            int(s.get("structure_swing", 3)),
        )
        dataframe = pd.concat([dataframe, struct], axis=1)
        daily_close = self._daily_close_for_vol(str(metadata.get("pair") or ""), dataframe)
        vol = lib.daily_realized_vol_percentiles(
            dataframe["close"],
            list(s.get("vol_windows_days", [5, 10, 20, 60, 120])),
            dates=dataframe["date"],
            daily_close=daily_close,
        )
        dataframe = pd.concat([dataframe, vol], axis=1)
        primary = int(s.get("vol_primary_window_days", 5))
        dataframe["vol_primary_pct"] = dataframe.get(f"vol_{primary}d_pct")
        last_pct = dataframe["vol_primary_pct"].iloc[-1] if len(dataframe) else float("nan")
        n_daily = int(daily_close.notna().sum()) if daily_close is not None else 0
        if not hasattr(self, "_vol_warmup_logged"):
            self._vol_warmup_logged = set()
        key = (str(metadata.get("pair") or ""), n_daily)
        if key not in self._vol_warmup_logged:
            self._vol_warmup_logged.add(key)
            logger.info(
                "MacdGatedFutures vol warmup pair=%s daily_bars=%s vol_primary_pct_last=%s",
                metadata.get("pair"),
                n_daily,
                "nan" if pd.isna(last_pct) else round(float(last_pct), 3),
            )

        inf_tf = self.informative_timeframe
        btc = s.get("btc_pair", "BTC/USDT:USDT")
        btc_1h = self.dp.get_pair_dataframe(pair=btc, timeframe=inf_tf)
        if btc_1h is not None and not btc_1h.empty:
            btc_1h = btc_1h.copy()
            btc_1h["btc_trend"] = lib.btc_trend_from_ohlc(
                btc_1h["close"], int(s.get("btc_ema", 50)), int(s.get("btc_slope_bars", 5))
            )
            dataframe = merge_informative_pair(
                dataframe, btc_1h[["date", "btc_trend"]], self.timeframe, inf_tf, ffill=True
            )
            # merge_informative_pair names the column btc_trend_1h
            if "btc_trend_1h" in dataframe.columns:
                dataframe["btc_trend"] = dataframe["btc_trend_1h"]
        if "btc_trend" not in dataframe.columns:
            dataframe["btc_trend"] = 0
        return dataframe

    def _vector_gate_frame(self, dataframe: DataFrame) -> DataFrame:
        s = self._settings()
        ranging = float(s.get("adx_ranging_below", 20))
        trending = float(s.get("adx_trending_above", 25))
        long_min = float(s.get("pressure_long_min", 0.60))
        short_max = float(s.get("pressure_short_max", 0.40))
        compressed = float(s.get("vol_compressed_percentile", 25))

        adx = dataframe["adx"]
        regime_range = adx < ranging
        regime_trend = adx > trending
        regime_trans = (~regime_range) & (~regime_trend)
        if TRANSITIONAL_POLICY == "allow":
            regime_ok = ~regime_range  # block only ADX<20
        else:
            regime_ok = regime_trend

        vol_pct = dataframe["vol_primary_pct"]
        vol_ok = vol_pct >= compressed
        # Insufficient history → fail-closed when the vol gate is on.
        vol_known = vol_pct.notna()

        pressure_long = (dataframe["buy_vol_pct"] > long_min) & (~dataframe["vol_anomaly"].fillna(False))
        pressure_short = (dataframe["buy_vol_pct"] < short_max) & (~dataframe["vol_anomaly"].fillna(False))

        out = dataframe.copy()
        out["gate_regime_ok"] = regime_ok & adx.notna()
        out["gate_regime_label"] = "ranging"
        out.loc[regime_trans, "gate_regime_label"] = "transitional_allowed"
        out.loc[regime_trend, "gate_regime_label"] = "trending"
        out.loc[regime_range, "gate_regime_label"] = "ranging"
        out["gate_vol_ok"] = vol_ok & vol_known
        out["gate_pressure_long_ok"] = pressure_long
        out["gate_pressure_short_ok"] = pressure_short
        out["gate_structure_long_ok"] = out["structure_long_ok"].astype(bool)
        out["gate_structure_short_ok"] = out["structure_short_ok"].astype(bool)
        trend = out["btc_trend"].fillna(0)
        out["gate_btc_long_ok"] = trend >= 0  # block only clear opposite
        out["gate_btc_short_ok"] = trend <= 0
        return out

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = self._vector_gate_frame(dataframe)
        raw_long = lib.cross_over_zero(df["macd_delta"])
        raw_short = lib.cross_under_zero(df["macd_delta"])
        g = self._gates()

        long_ok = raw_long.copy()
        short_ok = raw_short.copy()
        if g.get("regime", False):
            long_ok &= df["gate_regime_ok"]
            short_ok &= df["gate_regime_ok"]
        if g.get("volatility", False):
            long_ok &= df["gate_vol_ok"]
            short_ok &= df["gate_vol_ok"]
        if g.get("pressure", False):
            long_ok &= df["gate_pressure_long_ok"]
            short_ok &= df["gate_pressure_short_ok"]
        if g.get("structure", False):
            long_ok &= df["gate_structure_long_ok"]
            short_ok &= df["gate_structure_short_ok"]
        if g.get("btc_trend", False):
            long_ok &= df["gate_btc_long_ok"]
            short_ok &= df["gate_btc_short_ok"]

        dataframe["enter_long"] = long_ok.fillna(False)
        dataframe["enter_short"] = short_ok.fillna(False)
        dataframe["enter_tag"] = None
        dataframe.loc[long_ok.fillna(False), "enter_tag"] = "MacdLE"
        dataframe.loc[short_ok.fillna(False), "enter_tag"] = "MacdSE"

        if g.get("log_signals", True):
            self._log_raw_signals(df, metadata["pair"], raw_long, raw_short, long_ok, short_ok)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Opposite MACD cross closes the position; never gated.
        dataframe["exit_long"] = lib.cross_under_zero(dataframe["macd_delta"]).fillna(False)
        dataframe["exit_short"] = lib.cross_over_zero(dataframe["macd_delta"]).fillna(False)
        dataframe["exit_tag"] = None
        dataframe.loc[dataframe["exit_long"], "exit_tag"] = "MacdSE"
        dataframe.loc[dataframe["exit_short"], "exit_tag"] = "MacdLE"
        return dataframe

    def _log_raw_signals(
        self,
        df: DataFrame,
        pair: str,
        raw_long: pd.Series,
        raw_short: pd.Series,
        long_ok: pd.Series,
        short_ok: pd.Series,
    ) -> None:
        mask = (raw_long | raw_short).fillna(False)
        if not mask.any():
            return
        path = self._journal_path()
        cols = [
            "date",
            "close",
            "macd_delta",
            "adx",
            "buy_vol_pct",
            "vol_anomaly",
            "vol_primary_pct",
            "btc_trend",
            "gate_regime_label",
            "gate_regime_ok",
            "gate_vol_ok",
            "gate_pressure_long_ok",
            "gate_pressure_short_ok",
            "gate_structure_long_ok",
            "gate_structure_short_ok",
            "gate_btc_long_ok",
            "gate_btc_short_ok",
        ]
        use = [c for c in cols if c in df.columns]
        for idx in df.index[mask]:
            row = df.loc[idx, use].to_dict()
            is_long = bool(raw_long.loc[idx])
            lib.append_jsonl(
                path,
                {
                    "event": "raw_signal",
                    "pair": pair,
                    "side": "long" if is_long else "short",
                    "passed_vector_gates": bool(long_ok.loc[idx] if is_long else short_ok.loc[idx]),
                    **{k: (None if pd.isna(v) else v) for k, v in row.items()},
                    "gates_enabled": {k: bool(v) for k, v in self._gates().items()},
                },
            )

    def _closed_trades(self) -> list[Trade]:
        try:
            return list(Trade.get_trades_proxy(is_open=False))
        except Exception:  # pragma: no cover - persistence not ready
            return []

    def _open_trades(self) -> list[Trade]:
        try:
            return list(Trade.get_trades_proxy(is_open=True))
        except Exception:
            return []

    def _account_state(self, current_time: datetime) -> dict[str, Any]:
        start = float(self.config.get("dry_run_wallet", 1000))
        closed = self._closed_trades()
        opened = self._open_trades()
        closed_pnl = 0.0
        for t in closed:
            closed_pnl += float(t.close_profit_abs or 0.0)
        open_pnl = 0.0
        open_exposure = 0.0
        exposure_by_pair: dict[str, float] = {}
        for t in opened:
            stake = float(t.stake_amount or 0.0)
            open_exposure += stake
            exposure_by_pair[t.pair] = exposure_by_pair.get(t.pair, 0.0) + stake
            try:
                open_pnl += float(t.unrealized_profit or 0.0)
            except Exception:
                pass
        equity = start + closed_pnl + open_pnl
        # Peak: running peak of equity after each close (plus current).
        peak = start
        running = start
        for t in sorted(closed, key=lambda x: x.close_date or current_time):
            running += float(t.close_profit_abs or 0.0)
            peak = max(peak, running)
        peak = max(peak, equity)
        dd = 0.0 if peak <= 0 else max(0.0, (peak - equity) / peak)

        now = current_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        daily = 0.0
        for t in closed:
            cd = t.close_date
            if cd is None:
                continue
            if cd.tzinfo is None:
                cd = cd.replace(tzinfo=timezone.utc)
            if cd >= day_start:
                daily += float(t.close_profit_abs or 0.0)
        daily += open_pnl
        daily_pct = daily / start if start else 0.0

        consec = 0
        for t in sorted(closed, key=lambda x: x.close_date or current_time, reverse=True):
            pnl = float(t.close_profit_abs or 0.0)
            if pnl < 0:
                consec += 1
            else:
                break
        return {
            "equity": equity,
            "start": start,
            "peak": peak,
            "drawdown": dd,
            "daily_pct": daily_pct,
            "consecutive_losses": consec,
            "open_exposure": open_exposure,
            "exposure_by_pair": exposure_by_pair,
            "closed": closed,
        }

    def _risk_multiplier(self, state: dict[str, Any]) -> tuple[float, list[str]]:
        s = self._settings()
        reasons: list[str] = []
        mult = 1.0
        dd = state["drawdown"]
        if dd >= float(s.get("max_drawdown_pct", 0.15)):
            return 0.0, ["drawdown_halt"]
        if state["daily_pct"] <= -float(s.get("daily_loss_pct", 0.03)):
            return 0.0, ["daily_loss_stop"]
        if state["consecutive_losses"] >= int(s.get("consecutive_losses_pause", 7)):
            return 0.0, ["seven_loss_pause"]
        # DD bands: 5–10% scale 0.75→0.50; 10–15% minimum size.
        low = float(s.get("dd_caution_low", 0.05))
        high = float(s.get("dd_caution_high", 0.10))
        halt = float(s.get("max_drawdown_pct", 0.15))
        min_mult = float(s.get("min_size_mult", 0.25))
        if high <= dd < halt:
            mult = min(mult, min_mult)
            reasons.append("dd_10_15_min_size")
        elif low <= dd < high:
            # linear 25–50% reduction
            t = (dd - low) / (high - low) if high > low else 1.0
            sized = 0.75 - t * 0.25
            mult = min(mult, sized)
            reasons.append("dd_5_10_reduce")
        losses = state["consecutive_losses"]
        if losses >= int(s.get("consecutive_losses_min", 5)):
            mult = min(mult, min_mult)
            reasons.append("five_loss_min_size")
        elif losses >= int(s.get("consecutive_losses_half", 3)):
            mult = min(mult, 0.5)
            reasons.append("three_loss_half")
        return mult, reasons

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        state = self._account_state(current_time)
        s = self._settings()
        cap = float(s.get("single_coin_cap", 0.10)) * state["equity"]
        total_cap = float(s.get("total_exposure_cap", 0.80)) * state["equity"]
        already = state["exposure_by_pair"].get(pair, 0.0)
        remaining_pair = max(0.0, cap - already)
        remaining_total = max(0.0, total_cap - state["open_exposure"])
        base = min(cap, remaining_pair, remaining_total, max_stake)
        if self._gate_on("risk_limits"):
            # Volatility size-down when >75th (and further at 95th). Independent of vol entry block.
            vol_mult = 1.0
            if self._gate_on("volatility") or True:
                # Always honor size-down semantics when we can read last vol; harmless if NaN.
                pass
            # Use last analyzed candle vol if available via dp
            try:
                df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                if df is not None and not df.empty and "vol_primary_pct" in df.columns:
                    vp = df["vol_primary_pct"].iloc[-1]
                    elevated = float(s.get("vol_elevated_percentile", 75))
                    crisis = float(s.get("vol_crisis_percentile", 95))
                    if pd.notna(vp) and vp >= crisis:
                        vol_mult = 0.25
                    elif pd.notna(vp) and vp >= elevated:
                        # size down: 75→0.75x toward 95→0.50x
                        t = min(1.0, (float(vp) - elevated) / max(1.0, crisis - elevated))
                        vol_mult = 0.75 - t * 0.25
            except Exception:
                vol_mult = 1.0
            risk_mult, _ = self._risk_multiplier(state)
            base = base * risk_mult * vol_mult
        if min_stake and base < min_stake:
            return 0.0
        return float(max(0.0, base))

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        reasons: list[str] = []
        allowed = True
        s = self._settings()
        if self._gate_on("discipline"):
            window = timedelta(hours=float(s.get("revenge_window_hours", 24)))
            for t in self._closed_trades():
                if t.pair != pair:
                    continue
                cd = t.close_date
                if cd is None:
                    continue
                ct = current_time
                if cd.tzinfo is None:
                    cd = cd.replace(tzinfo=timezone.utc)
                if ct.tzinfo is None:
                    ct = ct.replace(tzinfo=timezone.utc)
                if ct - cd <= window and float(t.close_profit_abs or 0.0) < 0:
                    allowed = False
                    reasons.append("revenge_window_24h")
                    break
        if self._gate_on("risk_limits"):
            state = self._account_state(current_time)
            mult, rreasons = self._risk_multiplier(state)
            if mult <= 0:
                allowed = False
                reasons.extend(rreasons)
            # 7-loss 24h pause: if last 7 are losses, also require last close older than 24h
            if state["consecutive_losses"] >= int(s.get("consecutive_losses_pause", 7)):
                last = sorted(
                    [t for t in state["closed"] if t.close_date],
                    key=lambda x: x.close_date,
                )
                if last:
                    cd = last[-1].close_date
                    ct = current_time
                    if cd.tzinfo is None:
                        cd = cd.replace(tzinfo=timezone.utc)
                    if ct.tzinfo is None:
                        ct = ct.replace(tzinfo=timezone.utc)
                    if ct - cd < timedelta(hours=float(s.get("pause_hours", 24))):
                        allowed = False
                        reasons.append("seven_loss_24h_pause")
                    else:
                        # pause expired; allow at min size via multiplier path
                        pass
            cap = float(s.get("single_coin_cap", 0.10)) * state["equity"]
            total_cap = float(s.get("total_exposure_cap", 0.80)) * state["equity"]
            stake = amount * rate
            if state["exposure_by_pair"].get(pair, 0.0) + stake > cap * 1.001:
                allowed = False
                reasons.append("single_coin_cap_10pct")
            if state["open_exposure"] + stake > total_cap * 1.001:
                allowed = False
                reasons.append("total_exposure_cap_80pct")

        if self._gate_on("event_risk") or self._gate_on("circuit_breaker") or self._gate_on("crypto_regime"):
            ext_ok, ext_reasons = self._evaluate_external(current_time, side)
            if not ext_ok:
                allowed = False
                reasons.extend(ext_reasons)

        if self._gates().get("log_signals", True):
            lib.append_jsonl(
                self._journal_path(),
                {
                    "event": "entry_decision",
                    "pair": pair,
                    "side": side,
                    "allowed": allowed,
                    "reasons": reasons,
                    "entry_tag": entry_tag,
                    "time": current_time.isoformat(),
                    "rate": rate,
                    "amount": amount,
                },
            )
        return allowed

    def _evaluate_external(self, current_time: datetime, side: str) -> tuple[bool, list[str]]:
        s = self._settings()
        stale_map = s.get("gate_stale_minutes") or {}
        gates_dir = Path(self.config["user_data_dir"]) / "gates"
        reasons: list[str] = []
        now = current_time
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        if self._gate_on("event_risk"):
            info = lib.load_gate_file(
                gates_dir / "event_risk.json", int(stale_map.get("event_risk", 360)), now
            )
            if not info["ok"]:
                return False, [f"event_risk_fail_closed:{info['reason']}"]
            payload = info["payload"] or {}
            if payload.get("blocked") or payload.get("status") not in {"ok", "clear"}:
                return False, ["event_risk_blocked_or_unconfirmed"]

        if self._gate_on("circuit_breaker"):
            info = lib.load_gate_file(
                gates_dir / "circuit_breaker.json", int(stale_map.get("circuit_breaker", 15)), now
            )
            if not info["ok"]:
                return False, [f"circuit_breaker_fail_closed:{info['reason']}"]
            rec = str((info["payload"] or {}).get("recommendation") or "").upper()
            if rec != "TRADING_ALLOWED":
                return False, [f"circuit_breaker:{rec or 'missing'}"]

        if self._gate_on("crypto_regime"):
            info = lib.load_gate_file(
                gates_dir / "crypto_regime.json", int(stale_map.get("crypto_regime", 2160)), now
            )
            if not info["ok"]:
                return False, [f"crypto_regime_fail_closed:{info['reason']}"]
            zone = str((info["payload"] or {}).get("zone") or "").upper()
            # System policy (not claimed as the skill's own authorization rule):
            # RISK_OFF blocks longs; RISK_ON blocks shorts.
            if zone == "RISK_OFF" and side == "long":
                return False, ["crypto_regime_RISK_OFF_block_long"]
            if zone == "RISK_ON" and side == "short":
                return False, ["crypto_regime_RISK_ON_block_short"]
        return True, reasons
