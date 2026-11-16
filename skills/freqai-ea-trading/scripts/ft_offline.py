#!/usr/bin/env python3
"""Run a `freqtrade` backtest with two optional, backtest-only patches.

FT_OFFLINE=1 (default 1 when run directly): static market list.
    Freqtrade loads the exchange market list at start-up, even for backtesting. Where the
    exchange REST API is blocked this aborts with "Could not load markets". The patch
    injects a minimal Binance market list (spot + USDT-M) so backtesting works fully
    offline on data from download_binance_vision.py.

FT_FAST=1 (default 1): skip Freqtrade's defensive deep copy of the trade object.
    Freqtrade deep-copies `trade` (including every order) before each strategy callback
    (custom_stoploss runs on every 15m detail candle while a trade is open). The EAs only
    *read* the trade, so skipping the copy does not change results; it only makes them faster.

Only for backtesting / hyperopt. Never for dry-run or live trading.

Usage (same arguments as `freqtrade`):
  python ft_offline.py backtesting -c user_data/configs/config_btc_ea.json ...
"""

from __future__ import annotations

import os
import sys

BASES = os.environ.get(
    "FT_OFFLINE_BASES",
    "BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,LINK,DOT,LTC,TRX,SUI,NEAR,UNI,PEPE,WLD,ZEC,TON,APT",
).split(",")


def _market(base: str, quote: str, swap: bool) -> dict:
    symbol = f"{base}/{quote}:{quote}" if swap else f"{base}/{quote}"
    return {
        "id": f"{base}{quote}",
        "symbol": symbol,
        "base": base,
        "quote": quote,
        "settle": quote if swap else None,
        "baseId": base,
        "quoteId": quote,
        "settleId": quote if swap else None,
        "type": "swap" if swap else "spot",
        "spot": not swap,
        "margin": False,
        "swap": swap,
        "future": False,
        "option": False,
        "active": True,
        "contract": swap,
        "linear": True if swap else None,
        "inverse": False if swap else None,
        "contractSize": 1.0 if swap else None,
        "taker": 0.0005 if swap else 0.001,
        "maker": 0.0002 if swap else 0.001,
        "precision": {"amount": 1e-6, "price": 1e-6},
        "limits": {
            "amount": {"min": 1e-6, "max": None},
            "price": {"min": 1e-6, "max": None},
            "cost": {"min": 5.0, "max": None},
            "leverage": {"min": 1, "max": 20 if swap else 1},
        },
        "info": {},
    }


def _markets() -> dict:
    out = {}
    for base in BASES:
        for swap in (False, True):
            m = _market(base.strip(), "USDT", swap)
            out[m["symbol"]] = m
    return out


def patch() -> None:
    from freqtrade.exchange.exchange import Exchange

    def _load_async_markets(self, reload: bool = False) -> None:  # noqa: ARG001
        markets = _markets()
        self._api_async.set_markets(markets)

    Exchange._load_async_markets = _load_async_markets  # type: ignore[method-assign]

    # Backtesting never needs live tickers / fees from the API.
    def _get_fee(self, symbol, order_type="", side="", amount=1, price=1, taker_or_maker="maker"):  # noqa: ARG001
        m = self.markets.get(symbol, {})
        return float(m.get(taker_or_maker, 0.001))

    Exchange.get_fee = _get_fee  # type: ignore[method-assign]


def patch_fast() -> None:
    import freqtrade.strategy.strategy_wrapper as sw

    real_deepcopy = sw.deepcopy

    def _no_trade_copy(obj, memo=None):
        if obj.__class__.__name__ in ("LocalTrade", "Trade"):
            return obj
        return real_deepcopy(obj, memo)

    sw.deepcopy = _no_trade_copy


def main() -> None:
    if os.environ.get("FT_OFFLINE", "1") == "1":
        patch()
    if os.environ.get("FT_FAST", "1") == "1":
        patch_fast()
    from freqtrade.main import main as ft_main

    sys.argv = ["freqtrade", *sys.argv[1:]]
    ft_main()


if __name__ == "__main__":
    main()
