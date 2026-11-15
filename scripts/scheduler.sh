#!/usr/bin/env bash
# 啟動/停止/查詢 5 分鐘排程器（nohup + pidfile，不需要 systemd/cron）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRYPTO_TRADING_HOME="${CRYPTO_TRADING_HOME:-$(cd "$ROOT/.." && pwd)}"
PY="${CRYPTO_TRADING_HOME}/venvs/pionex-trading-skills/bin/python"
PIDFILE="$ROOT/logs/scheduler.pid"; LOG="$ROOT/logs/scheduler.log"
mkdir -p "$ROOT/logs"
alive() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
case "${1:-status}" in
  start) if alive; then echo "already running pid $(cat "$PIDFILE")"; exit 0; fi
         PIONEX_MACD_HOME="$ROOT" setsid nohup "$PY" "$ROOT/scripts/scheduler.py" >>"$LOG" 2>&1 &
         echo $! > "$PIDFILE"; echo "started pid $!";;
  stop)  if alive; then kill "$(cat "$PIDFILE")"; echo stopped; else echo "not running"; fi; rm -f "$PIDFILE";;
  restart) "$0" stop; "$0" start;;
  once)  PIONEX_MACD_HOME="$ROOT" "$PY" "$ROOT/scripts/scheduler.py" --once;;
  status) if alive; then echo "running pid $(cat "$PIDFILE")"; else echo "not running"; fi
          [[ -f "$ROOT/logs/scheduler_heartbeat.json" ]] && cat "$ROOT/logs/scheduler_heartbeat.json"; true;;
  *) echo "usage: $0 start|stop|restart|status|once"; exit 2;;
esac
