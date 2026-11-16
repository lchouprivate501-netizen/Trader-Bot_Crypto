#!/usr/bin/env bash
# Walk-forward FreqAI backtest of one coin grid + mark-to-market report.
#   bash backtest.sh <btc|eth|sol> [timerange] [split-date]
# Defaults: timerange 20210601-20261101, split 2024-12-12 (in-sample / out-of-sample;
# 2024-12-12 = 20210601 + 43 FreqAI windows of 30 days, the end of the tuning range).
# Env: FT_VENV, FT_HOME as in setup_env.sh; FT_OFFLINE=1 uses the offline market list
#      (only needed where the exchange API is unreachable; backtesting only).
set -euo pipefail

COIN="${1:?usage: backtest.sh <btc|eth|sol> [timerange] [split-date]}"
TIMERANGE="${2:-20210601-20261101}"
SPLIT="${3:-2024-12-12}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FT_VENV="${FT_VENV:-$HOME/crypto-trading/venvs/freqai-grid}"
FT_HOME="${FT_HOME:-$HOME/crypto-trading/freqai-grid/user_data}"
PY="$FT_VENV/bin/python"
CONFIG="$SKILL_DIR/user_data/configs/config_${COIN}.json"

case "$COIN" in
  btc) FEE=0.001 ;;   # Binance spot VIP0 (maker = taker 0.10%)
  eth|sol) FEE=0.001 ;;  # Binance spot VIP0 0.10% (all three grids run on spot)
  *) echo "unknown coin $COIN" >&2; exit 2 ;;
esac

# ft_offline.py = freqtrade + backtest-only speed patch (FT_FAST); FT_OFFLINE=1 also swaps in
# a static market list for networks where the exchange API is blocked.
RUN=(env "FT_OFFLINE=${FT_OFFLINE:-0}" "FT_FAST=${FT_FAST:-1}" "$PY" "$SKILL_DIR/scripts/ft_offline.py")

# Every FreqAI identifier caches one prediction file per 30-day window, anchored at the
# timerange start. Keep the start fixed (20210601) when comparing runs; an end date that is
# not start + k*30 days makes the last window retrain (harmless, but slower).

"${RUN[@]}" backtesting -c "$CONFIG" --userdir "$FT_HOME" \
  --strategy-path "$SKILL_DIR/user_data/strategies" \
  --freqaimodel-path "$SKILL_DIR/user_data/freqaimodels" \
  --timerange "$TIMERANGE" --fee "$FEE" --cache none --export trades

mkdir -p "$FT_HOME/grid_reports"
"$PY" "$SKILL_DIR/scripts/grid_report.py" --results-dir "$FT_HOME/backtest_results" --split "$SPLIT" \
  --json "$FT_HOME/grid_reports/${COIN}.json" --md "$FT_HOME/grid_reports/${COIN}.md"
