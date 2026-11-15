#!/usr/bin/env bash
# Trader 私人交易公司：一鍵安裝（可重複執行）。只從官方來源下載，不使用 curl | bash。
#  1) uv：astral-sh/uv 官方 GitHub release（驗證 sha256）
#  2) Python 3.13 venv：$CRYPTO_TRADING_HOME/venvs/pionex-trading-skills
#  3) nautilus_trader / optuna / mcp 等（PyPI，版本鎖定在 mcp/pyproject.toml）
#  4) 下載 OKX 公開 K 線（不需金鑰）並啟動 5 分鐘排程器
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CRYPTO_TRADING_HOME="${CRYPTO_TRADING_HOME:-$(cd "$ROOT/.." && pwd)}"
VENV="$CRYPTO_TRADING_HOME/venvs/pionex-trading-skills"
UV_VERSION="0.13.8"
UV_SHA256="5acfd9177cfecf0bf87578f059728215ccc884388988f55f7a65041b57387d91"
DAYS="${DAYS:-365}"

say() { printf '\n==> %s\n' "$*"; }

if ! command -v uv >/dev/null 2>&1; then
  say "安裝 uv ${UV_VERSION}（GitHub release）"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/uv.tgz" "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
  echo "${UV_SHA256}  $tmp/uv.tgz" | sha256sum -c -
  tar -xzf "$tmp/uv.tgz" -C "$tmp"
  mkdir -p "$HOME/.local/bin"
  install -m 0755 "$tmp"/uv-x86_64-unknown-linux-gnu/uv "$tmp"/uv-x86_64-unknown-linux-gnu/uvx "$HOME/.local/bin/"
  export PATH="$HOME/.local/bin:$PATH"
fi

say "建立 Python 3.13 虛擬環境 $VENV"
mkdir -p "$(dirname "$VENV")"
[[ -x "$VENV/bin/python" ]] || uv venv --python 3.13 "$VENV"
VIRTUAL_ENV="$VENV" uv pip install -e "$ROOT/mcp"
"$VENV/bin/python" -c "import nautilus_trader, optuna, mcp; print('nautilus_trader', nautilus_trader.__version__, '/ optuna', optuna.__version__)"

say "下載 OKX 公開 5m K 線 ${DAYS} 天（約 1 小時，可中斷後重跑，會增量續傳）"
cd "$ROOT"
PIONEX_MACD_HOME="$ROOT" "$VENV/bin/python" -m rnd.data --days "$DAYS" --tf 5m

say "MCP 煙霧測試"
"$VENV/bin/python" scripts/mcp_smoke.py

say "啟動 5 分鐘排程器"
bash scripts/scheduler.sh start

cat <<MSG

完成。接下來：
- 在 Grok Bot 加入 stdio MCP 連接器：
    command: $VENV/bin/python
    args:    -m pionex_trading_skills
    env:     PIONEX_MACD_HOME=$ROOT  CRYPTO_TRADING_HOME=$CRYPTO_TRADING_HOME
- 跑研發流水線：  $VENV/bin/python -m rnd.pipeline vwap_pullback --trials 60
- Trader 的每輪流程見 docs/TRADER_PLAYBOOK.md
MSG
