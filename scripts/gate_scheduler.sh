#!/usr/bin/env bash
# Start/stop/restart the UTC gatekeeper loop (no systemd required).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRYPTO_TRADING_HOME="${CRYPTO_TRADING_HOME:-$(cd "$ROOT/.." && pwd)}"
VENV="${CRYPTO_TRADING_HOME}/venvs/pionex-trading-skills"
PY="${VENV}/bin/python"
LOG_DIR="${ROOT}/user_data/logs"
PIDFILE="${LOG_DIR}/gate-scheduler.pid"
LOGFILE="${LOG_DIR}/gate-scheduler.log"
export PIONEX_MACD_HOME="$ROOT"
export CRYPTO_TRADING_HOME
export PIONEX_MCP_BIN="${VENV}/bin"

mkdir -p "$LOG_DIR"

is_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

pid_from_file() {
  [[ -f "$PIDFILE" ]] || return 0
  tr -d '[:space:]' < "$PIDFILE" || true
}

cmd_status() {
  local pid
  pid="$(pid_from_file)"
  if is_alive "${pid:-}"; then
    echo "running pid=$pid"
    return 0
  fi
  echo "stopped"
  return 1
}

cmd_stop() {
  local pid
  pid="$(pid_from_file)"
  if is_alive "${pid:-}"; then
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      is_alive "$pid" || break
      sleep 0.2
    done
    if is_alive "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$PIDFILE"
  echo "stopped"
}

cmd_start() {
  if cmd_status >/dev/null; then
    echo "already running pid=$(pid_from_file)"
    return 0
  fi
  if [[ ! -x "$PY" ]]; then
    echo "missing venv python: $PY" >&2
    return 1
  fi
  nohup "$PY" "$ROOT/scripts/gate_scheduler.py" >>"$LOGFILE" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 0.3
  if is_alive "$(pid_from_file)"; then
    echo "started pid=$(pid_from_file)"
    return 0
  fi
  echo "failed to start; see $LOGFILE" >&2
  return 1
}

cmd_restart() {
  cmd_stop
  cmd_start
}

case "${1:-status}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  *) echo "usage: $0 {start|stop|restart|status}" >&2; exit 2 ;;
esac
