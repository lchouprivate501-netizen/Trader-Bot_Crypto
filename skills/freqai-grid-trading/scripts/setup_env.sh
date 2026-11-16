#!/usr/bin/env bash
# Install a pinned Freqtrade + FreqAI environment for the freqai-grid-trading skill.
#   FT_VENV   venv path            (default: ~/crypto-trading/venvs/freqai-grid)
#   FT_HOME   freqtrade userdir    (default: ~/crypto-trading/freqai-grid/user_data)
# Idempotent. Needs Python 3.12+ (3.13 recommended) and either `uv` or `python3 -m venv`.
set -euo pipefail

FT_VERSION="${FT_VERSION:-2026.10}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FT_VENV="${FT_VENV:-$HOME/crypto-trading/venvs/freqai-grid}"
FT_HOME="${FT_HOME:-$HOME/crypto-trading/freqai-grid/user_data}"

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

say "userdir $FT_HOME (strategies / models / configs are symlinked from the skill)"
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
Next:
  $FT_VENV/bin/python $SKILL_DIR/scripts/download_binance_vision.py --trading-mode spot \
      --timeframes 1h 5m --start 2020-06 --datadir $FT_HOME/data/binance
  FT_VENV=$FT_VENV FT_HOME=$FT_HOME bash $SKILL_DIR/scripts/backtest.sh btc 20210601-20261101 2024-12-12
  (FT_OFFLINE=1 in front of backtest.sh if the exchange API is unreachable from this machine)
MSG
