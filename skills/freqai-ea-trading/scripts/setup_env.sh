#!/usr/bin/env bash
# Install a pinned Freqtrade + FreqAI environment for the BTC / ETH / SOL EAs.
#   FT_VENV   venv path            (default: ~/crypto-trading/venvs/freqai-ea)
#   FT_HOME   freqtrade userdir    (default: ~/crypto-trading/freqai-ea/user_data; for backtests)
# Idempotent. Needs Python 3.12+ (3.13 recommended) and either `uv` or `python3 -m venv`.
set -euo pipefail

FT_VERSION="${FT_VERSION:-2026.10}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FT_VENV="${FT_VENV:-$HOME/crypto-trading/venvs/freqai-ea}"
FT_HOME="${FT_HOME:-$HOME/crypto-trading/freqai-ea/user_data}"

say() { printf '\n==> %s\n' "$*"; }

say "venv $FT_VENV (freqtrade[freqai]==$FT_VERSION)"
mkdir -p "$(dirname "$FT_VENV")"
if command -v uv >/dev/null 2>&1; then
  [[ -x "$FT_VENV/bin/python" ]] || uv venv --python 3.13 "$FT_VENV"
  VIRTUAL_ENV="$FT_VENV" uv pip install "freqtrade[freqai,hyperopt]==${FT_VERSION}"
else
  [[ -x "$FT_VENV/bin/python" ]] || python3 -m venv "$FT_VENV"
  "$FT_VENV/bin/pip" install -U pip
  "$FT_VENV/bin/pip" install "freqtrade[freqai,hyperopt]==${FT_VERSION}"
fi
"$FT_VENV/bin/freqtrade" --version

say "userdir $FT_HOME (for backtests; strategies / models / configs are symlinked from the skill)"
"$FT_VENV/bin/freqtrade" create-userdir --userdir "$FT_HOME" >/dev/null
for sub in strategies freqaimodels; do
  for f in "$SKILL_DIR/user_data/$sub/"*.py; do
    ln -sf "$f" "$FT_HOME/$sub/$(basename "$f")"
  done
done
mkdir -p "$FT_HOME/configs"
for f in "$SKILL_DIR/user_data/configs/"*.json; do
  ln -sf "$f" "$FT_HOME/configs/$(basename "$f")"
done

cat <<MSG

Done.
  FT_VENV=$FT_VENV
  FT_HOME=$FT_HOME
Let an AI trade the EAs (key-less engines + guard):
  python3 $SKILL_DIR/desk/ea_engine.py start
Backtest / validate (download data first):
  $FT_VENV/bin/python $SKILL_DIR/scripts/download_binance_vision.py --pairs BTC/USDT ETH/USDT SOL/USDT \\
      --timeframes 1h 15m --start 2020-06 --datadir $FT_HOME/data/binance
  $FT_VENV/bin/python $SKILL_DIR/scripts/ea_lab.py backtest --coin btc --userdir $FT_HOME
  (FT_OFFLINE=1 in front if the exchange API is unreachable from this machine)
MSG
