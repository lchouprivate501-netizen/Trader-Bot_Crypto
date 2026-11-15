"""研發部「回測」角色：用 nautilus_trader BacktestEngine 做組合層級回測。
- 所有幣種放進同一個保證金帳戶（USDT，2 倍），手續費 maker=taker=0.05%（Trader 用市價單，保守）。
- 訊號在 5m 收盤時產生，以市價進場並同時掛停損（stop-market）與停利（limit）。
- 硬性風控和實盤一致：每筆風險 0.5% 權益、單幣保證金 ≤10%、最多 3 倉、單日已實現虧損 3% 當日停新單、
  連虧 7 筆暫停 24h、回撤 15% 停機（HALT）。"""
from __future__ import annotations
from decimal import Decimal
import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, TraderId
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.trading.strategy import Strategy

from company.paths import risk_caps

VENUE = Venue("OKX")


def make_instrument(sym: str, px: float, fee: float) -> CryptoPerpetual:
    pp = max(1, min(9, 6 - int(f"{px:e}".split("e")[1])))  # ~6 significant digits
    sp = max(0, min(6, int(f"{px:e}".split("e")[1]) + 2))
    return CryptoPerpetual(
        instrument_id=InstrumentId(Symbol(f"{sym}USDT-PERP"), VENUE), raw_symbol=Symbol(f"{sym}-USDT-SWAP"),
        base_currency=_ccy(sym),
        quote_currency=USDT, settlement_currency=USDT, is_inverse=False,
        price_precision=pp, size_precision=sp, price_increment=Price(10 ** -pp, pp), size_increment=Quantity(10 ** -sp, sp),
        ts_event=0, ts_init=0, margin_init=Decimal("0.5"), margin_maint=Decimal("0.01"),
        maker_fee=Decimal(str(fee)), taker_fee=Decimal(str(fee)))


def _ccy(sym):
    from nautilus_trader.model.objects import Currency
    from nautilus_trader.model.enums import CurrencyType
    try:
        return Currency.from_str(sym)
    except Exception:
        return Currency(sym, 8, 0, sym, CurrencyType.CRYPTO)


class SignalStratConfig(StrategyConfig, frozen=True):
    max_hold: int = 36


class SignalStrategy(Strategy):
    """Consumes precomputed signals {instrument_id: DataFrame indexed by bar ts_event(ns)}."""

    def __init__(self, config: SignalStratConfig, signals: dict, bar_types: list, caps: dict):
        super().__init__(config)
        self.sigs, self.bar_types, self.caps = signals, bar_types, caps
        self.open_since: dict = {}
        self.day, self.day_start_eq = None, None
        self.loss_streak, self.pause_until, self.halted = 0, 0, False
        self.peak = None
        self.blocked = {"daily": 0, "streak": 0, "max_pos": 0, "halt": 0}

    def on_start(self):
        for bt in self.bar_types:
            self.subscribe_bars(bt)

    def equity(self) -> float:
        acct = self.portfolio.account(VENUE)
        bal = float(acct.balance_total(USDT).as_double())
        upnl = sum(float(self.portfolio.unrealized_pnl(i).as_double() if self.portfolio.unrealized_pnl(i) else 0)
                   for i in self.sigs)
        return bal + upnl

    def on_position_closed(self, event):
        pnl = float(event.realized_pnl.as_double())
        self.loss_streak = self.loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak >= self.caps["max_consecutive_losses"]:
            self.pause_until = event.ts_event + int(self.caps["consecutive_loss_pause_hours"] * 3600e9)
            self.loss_streak = 0
        self.cancel_all_orders(event.instrument_id)

    def on_bar(self, bar: Bar):
        iid = bar.bar_type.instrument_id
        t = bar.ts_event
        eq = self.equity()
        self.peak = max(self.peak or eq, eq)
        if self.peak and (self.peak - eq) / self.peak * 100 >= self.caps["max_drawdown_halt_pct"]:
            if not self.halted:
                self.halted = True
                self.close_all_positions(iid); 
        d = t // int(86400e9)
        if d != self.day:
            self.day, self.day_start_eq = d, float(self.portfolio.account(VENUE).balance_total(USDT).as_double())
        # time stop
        if not self.portfolio.is_flat(iid):
            if iid in self.open_since and t - self.open_since[iid] >= self.config.max_hold * 300e9:
                self.cancel_all_orders(iid)
                self.close_all_positions(iid)
            return
        s = self.sigs[iid]
        row = s.get(t)
        if row is None:
            return
        side = 1 if row[0] else (-1 if row[1] else 0)
        if side == 0:
            return
        if self.halted:
            self.blocked["halt"] += 1; return
        if t < self.pause_until:
            self.blocked["streak"] += 1; return
        bal = float(self.portfolio.account(VENUE).balance_total(USDT).as_double())
        if (self.day_start_eq - bal) / self.day_start_eq * 100 >= self.caps["daily_realized_loss_stop_pct"]:
            self.blocked["daily"] += 1; return
        n_open = sum(0 if self.portfolio.is_flat(i) else 1 for i in self.sigs)
        if n_open >= self.caps["max_open_positions"]:
            self.blocked["max_pos"] += 1; return
        entry = bar.close.as_double()
        sl, tp = (row[2], row[3]) if side == 1 else (row[4], row[5])
        risk = abs(entry - sl)
        inst = self.cache.instrument(iid)
        qty = eq * self.caps["max_risk_per_trade_pct"] / 100 / risk
        max_notional = eq * self.caps["max_single_coin_margin_pct"] / 100 * self.caps["leverage"]
        qty = min(qty, max_notional / entry)
        q = inst.make_qty(qty)
        if q.as_double() <= 0:
            return
        order = self.order_factory.bracket(
            instrument_id=iid, order_side=OrderSide.BUY if side == 1 else OrderSide.SELL, quantity=q,
            sl_trigger_price=inst.make_price(sl), tp_price=inst.make_price(tp), time_in_force=TimeInForce.GTC)
        self.submit_order_list(order)
        self.open_since[iid] = t


def run(frames: dict, signals: dict, max_hold: int, fee: float, start_equity: float = 10_000.0, log_level: str = "ERROR"):
    """frames/signals: {sym: df}; df has ts + OHLCV; signals aligned to df rows. Returns (positions_df, account_df, extra)."""
    caps = risk_caps()
    eng = BacktestEngine(BacktestEngineConfig(trader_id=TraderId("RND-001"), logging=LoggingConfig(log_level=log_level)))
    eng.add_venue(venue=VENUE, oms_type=OmsType.NETTING, account_type=AccountType.MARGIN, base_currency=USDT,
                  starting_balances=[Money(start_equity, USDT)], default_leverage=Decimal(caps["leverage"]),
                  bar_execution=True)
    sigmap, bar_types = {}, []
    for sym, df in frames.items():
        inst = make_instrument(sym, float(df.close.iloc[-1]), fee)
        eng.add_instrument(inst)
        bt = BarType.from_str(f"{inst.id}-5-MINUTE-LAST-EXTERNAL")
        d = df.set_index("ts")[["open", "high", "low", "close", "volume"]].copy()
        d.index = d.index + pd.Timedelta(minutes=5)  # ts_event = bar close
        bars = BarDataWrangler(bt, inst).process(d)
        eng.add_data(bars)
        s = signals[sym]
        keys = (d.index.astype("int64")).values
        vals = s[["long", "short", "sl_long", "tp_long", "sl_short", "tp_short"]].values
        m = s.long.values | s.short.values
        sigmap[inst.id] = {int(k): tuple(v) for k, v, f in zip(keys, vals, m) if f}
        bar_types.append(bt)
    strat = SignalStrategy(SignalStratConfig(max_hold=max_hold), sigmap, bar_types, caps)
    eng.add_strategy(strat)
    eng.run()
    pos = eng.trader.generate_positions_report()
    acct = eng.trader.generate_account_report(VENUE)
    extra = {"blocked": strat.blocked, "halted": strat.halted}
    eng.dispose()
    return pos, acct, extra
