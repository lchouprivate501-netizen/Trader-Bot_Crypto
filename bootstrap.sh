#!/usr/bin/env bash
# Idempotent bootstrap for the pionex-macd template.
# Official sources only: Docker apt (download.docker.com), two GitHub skill repos,
# graphifyy from PyPI, freqtradeorg/freqtrade:stable_freqai.
# Never pipes curl to a shell. Does not change SSH or firewall settings.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRYPTO_TRADING_HOME="${CRYPTO_TRADING_HOME:-$(cd "$ROOT/.." && pwd)}"
REPOS="${CRYPTO_TRADING_HOME}/repos"
VENV="${CRYPTO_TRADING_HOME}/venvs/pionex-trading-skills"
PY="${PYTHON:-python3}"

log() { printf '%s\n' "$*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少指令：$1" >&2; exit 1; }
}

install_docker_if_needed() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    log "Docker 已安裝：$(docker --version)"
    return 0
  fi
  if [[ "$(id -u)" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
    echo "需要 Docker，但此帳號無法無密碼使用 sudo。請先安裝 Docker Engine + Compose plugin。" >&2
    exit 1
  fi
  SUDO="sudo"
  command -v curl >/dev/null
  $SUDO apt-get install -y ca-certificates curl
  $SUDO install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    $SUDO curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    $SUDO chmod a+r /etc/apt/keyrings/docker.asc
  fi
  . /etc/os-release
  if [[ ! -f /etc/apt/sources.list.d/docker.sources ]]; then
    $SUDO tee /etc/apt/sources.list.d/docker.sources >/dev/null <<SRC
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
SRC
  fi
  $SUDO apt-get update
  $SUDO apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

docker_ready() {
  docker info >/dev/null 2>&1 || sudo docker info >/dev/null 2>&1
}

ensure_docker_group() {
  if ! getent group docker >/dev/null 2>&1; then
    sudo groupadd docker || true
  fi
  local user_name="${SUDO_USER:-${USER:-$(id -un)}}"
  if id -nG "$user_name" 2>/dev/null | tr " " "\n" | grep -qx docker; then
    return 0
  fi
  sudo usermod -aG docker "$user_name"
  log "已將 $user_name 加入 docker 群組。目前 shell 若仍無權限，請重新登入或執行：sg docker -c 'docker ps'"
}

start_dockerd_if_needed() {
  ensure_docker_group
  if docker_ready; then
    return 0
  fi
  if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running >/dev/null 2>&1; then
    sudo systemctl start docker || sudo systemctl restart docker || true
  else
    # No systemd: restart a stale dockerd, then start one with group docker.
    sudo mkdir -p /var/log /var/run
    if pgrep -x dockerd >/dev/null 2>&1; then
      log "dockerd 無回應，嘗試重啟（無 systemd）"
      sudo pkill -TERM -x dockerd || true
      for _ in 1 2 3 4 5; do
        pgrep -x dockerd >/dev/null 2>&1 || break
        sleep 1
      done
      if pgrep -x dockerd >/dev/null 2>&1; then
        sudo pkill -KILL -x dockerd || true
        sleep 1
      fi
    fi
    sudo sh -c 'dockerd -G docker --log-level=info >> /var/log/dockerd.log 2>&1' &
  fi
  for _ in $(seq 1 20); do
    if docker_ready; then
      return 0
    fi
    sleep 1
  done
  echo "無法啟動 dockerd，請查看 /var/log/dockerd.log" >&2
  exit 1
}

clone_repo() {
  local url="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ -d "$dest/.git" ]]; then
    git -C "$dest" fetch --depth 1 origin || true
    log "已存在：$dest ($(git -C "$dest" rev-parse --short HEAD))"
  else
    git clone --depth 1 "$url" "$dest"
  fi
}

need_cmd git
need_cmd "$PY"
install_docker_if_needed
start_dockerd_if_needed

mkdir -p "$REPOS" "${CRYPTO_TRADING_HOME}/venvs" "$ROOT/user_data/gates" "$ROOT/user_data/logs" "$ROOT/graphify-out" "$ROOT/state"
if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  chmod 600 "$ROOT/.env"
  log "已建立 $ROOT/.env（空白欄位，權限 600）。請自行填寫，不要在聊天中貼金鑰。"
fi
if [[ ! -f "$ROOT/state/mode" ]]; then
  printf 'PAPER\n' > "$ROOT/state/mode"
  log "已建立 $ROOT/state/mode=PAPER"
fi
if [[ ! -f "$ROOT/state/ledger.csv" ]]; then
  printf 'fill_id,ts_utc,mode,position_id,signal_id,pair,side,action,qty,price,leverage,fee_usdt,stop_price,realized_pnl_usdt,reason,note\n' > "$ROOT/state/ledger.csv"
fi
if [[ ! -f "$ROOT/state/.gitkeep" ]]; then
  : > "$ROOT/state/.gitkeep"
fi

clone_repo https://github.com/tradermonty/claude-trading-skills.git "$REPOS/claude-trading-skills"
clone_repo https://github.com/agiprolabs/claude-trading-skills.git "$REPOS/agiprolabs-trading-skills"

DOCKER=docker
sudo docker info >/dev/null 2>&1 && DOCKER="sudo docker"
$DOCKER pull freqtradeorg/freqtrade:stable_freqai

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -e "$ROOT/mcp"

# Record versions
VER="$ROOT/VERSIONS.md"
{
  echo "# pionex-macd 版本紀錄"
  echo
  echo "產生時間：$(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo
  echo "## Docker"
  $DOCKER version --format 'Engine {{.Server.Version}} / CLI {{.Client.Version}}' || $DOCKER --version
  $DOCKER compose version || true
  echo
  echo "## 映像 freqtradeorg/freqtrade:stable_freqai"
  $DOCKER image inspect freqtradeorg/freqtrade:stable_freqai --format 'digest={{index .RepoDigests 0}} created={{.Created}}'
  $DOCKER run --rm freqtradeorg/freqtrade:stable_freqai --version || true
  echo
  echo "## Git"
  echo "- tradermonty/claude-trading-skills $(git -C "$REPOS/claude-trading-skills" rev-parse HEAD)"
  echo "- agiprolabs/claude-trading-skills $(git -C "$REPOS/agiprolabs-trading-skills" rev-parse HEAD)"
  echo
  echo "## Python venv $VENV"
  "$VENV/bin/pip" freeze
} > "$VER"
log "已寫入 $VER"

# Pin requirements from the live venv (no machine-local editable paths)
"$VENV/bin/pip" freeze | grep -vE '^-e ' > "$ROOT/mcp/requirements.lock" || true

# Code-only knowledge graph (no LLM). Safe to re-run.
if [[ -x "$VENV/bin/graphify" ]]; then
  (cd "$ROOT" && GRAPHIFY_BACKEND=none "$VENV/bin/graphify" update . --force) || log "graphify update 失敗，可稍後再跑"
fi

cat <<CFG

===== 請把以下 MCP 設定加到 bot / Claude / Cursor 的 MCP 清單 =====

{
  "mcpServers": {
    "pionex-trading-skills": {
      "command": "$VENV/bin/python",
      "args": ["-m", "pionex_trading_skills"],
      "env": {
        "PIONEX_MACD_HOME": "$ROOT",
        "CRYPTO_TRADING_HOME": "$CRYPTO_TRADING_HOME",
        "PIONEX_SKILLS_TRADERMONTY": "$REPOS/claude-trading-skills",
        "PIONEX_SKILLS_AGIPROLABS": "$REPOS/agiprolabs-trading-skills",
        "GRAPHIFY_GRAPH": "$ROOT/graphify-out/graph.json"
      }
    },
    "graphify": {
      "command": "$VENV/bin/graphify-mcp",
      "args": ["--graph", "$ROOT/graphify-out/graph.json", "--transport", "stdio"],
      "env": {
        "GRAPHIFY_BACKEND": "none"
      }
    }
  }
}

路徑依這台機器的安裝位置展開（腳本使用倉庫根目錄，沒有寫死某一使用者家目錄）。
接下來請閱讀 $ROOT/INSTALL.md。
CFG
