#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_MODULE="${APP_MODULE:-app.main:app}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
UV_BIN="${UV_BIN:-uv}"
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

RUN_DIR="${RUN_DIR:-${BACKEND_DIR}/run}"
LOG_DIR="${LOG_DIR:-${BACKEND_DIR}/logs}"
PID_FILE="${PID_FILE:-${RUN_DIR}/uvicorn.pid}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/uvicorn.log}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${PORT}/api/health}"
HEALTH_CHECK="${HEALTH_CHECK:-true}"
STOP_TIMEOUT="${STOP_TIMEOUT:-20}"

usage() {
  cat <<EOF
Usage: $(basename "$0") <start|stop|restart|status|logs>

Environment overrides:
  HOST=0.0.0.0                   Bind host.
  PORT=8000                      Bind port.
  WORKERS=1                      Uvicorn worker count.
  APP_MODULE=app.main:app        ASGI app module.
  UV_BIN=uv                      uv executable.
  RUN_DIR=${BACKEND_DIR}/run
  LOG_DIR=${BACKEND_DIR}/logs
  PID_FILE=${RUN_DIR}/uvicorn.pid
  LOG_FILE=${LOG_DIR}/uvicorn.log
  HEALTH_URL=http://127.0.0.1:8000/api/health
  HEALTH_CHECK=true              Set to false to skip curl health check after start.
  UV_CACHE_DIR=""                Optional uv cache directory if the service user's home is not writable.
  UVICORN_ARGS=""                Extra uvicorn arguments.

Examples:
  scripts/server.sh start
  scripts/server.sh status
  scripts/server.sh logs
  HOST=127.0.0.1 PORT=8000 scripts/server.sh restart
EOF
}

ensure_dirs() {
  mkdir -p "$RUN_DIR" "$LOG_DIR"
}

read_pid() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid="$(tr -d '[:space:]' < "$PID_FILE")"
  if [[ -z "$pid" || ! "$pid" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  printf '%s' "$pid"
}

is_running() {
  local pid
  pid="$(read_pid)" || return 1
  local state
  state="$(ps -o stat= -p "$pid" 2>/dev/null | awk '{print $1}')"
  if [[ "$state" == Z* ]]; then
    return 1
  fi
  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if command -v pgrep >/dev/null 2>&1 && pgrep -g "$pid" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

terminate_process_group() {
  local signal="$1"
  local pid="$2"
  kill "-${signal}" -- "-${pid}" 2>/dev/null || kill "-${signal}" "$pid" 2>/dev/null || true
}

wait_for_health() {
  case "$HEALTH_CHECK" in
    0|false|False|no|NO)
      sleep 1
      is_running
      return
      ;;
  esac

  if ! command -v curl >/dev/null 2>&1; then
    sleep 1
    is_running
    return
  fi

  for _ in {1..30}; do
    if ! is_running; then
      return 1
    fi
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

start_server() {
  ensure_dirs
  if is_running; then
    echo "FastAPI is already running. pid=$(read_pid)"
    return 0
  fi

  rm -f "$PID_FILE"
  cd "$BACKEND_DIR"

  if ! command -v setsid >/dev/null 2>&1; then
    echo "setsid is required to start the service as an isolated process group." >&2
    return 1
  fi

  echo "Starting FastAPI..."
  echo "  app:    ${APP_MODULE}"
  echo "  bind:   ${HOST}:${PORT}"
  echo "  log:    ${LOG_FILE}"
  echo "  health: ${HEALTH_URL}"

  # shellcheck disable=SC2086
  nohup setsid "$UV_BIN" run uvicorn "$APP_MODULE" \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --proxy-headers \
    --forwarded-allow-ips "$FORWARDED_ALLOW_IPS" \
    ${UVICORN_ARGS:-} \
    >> "$LOG_FILE" 2>&1 &

  local pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"

  if wait_for_health; then
    echo "FastAPI started. pid=${pid}"
    return 0
  fi

  echo "FastAPI failed to become healthy. See log: ${LOG_FILE}" >&2
  if is_running; then
    terminate_process_group TERM "$pid"
  fi
  rm -f "$PID_FILE"
  tail -n 80 "$LOG_FILE" >&2 || true
  return 1
}

stop_server() {
  local pid
  pid="$(read_pid)" || {
    echo "FastAPI is not running. No pid file: ${PID_FILE}"
    return 0
  }

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "FastAPI is not running. Removing stale pid file."
    rm -f "$PID_FILE"
    return 0
  fi

  echo "Stopping FastAPI... pid=${pid}"
  terminate_process_group TERM "$pid"

  for ((i = 0; i < STOP_TIMEOUT; i += 1)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "FastAPI stopped."
      return 0
    fi
    sleep 1
  done

  echo "FastAPI did not stop within ${STOP_TIMEOUT}s; killing pid=${pid}."
  terminate_process_group KILL "$pid"
  rm -f "$PID_FILE"
}

status_server() {
  local pid
  pid="$(read_pid)" || {
    echo "FastAPI is stopped. No pid file: ${PID_FILE}"
    return 3
  }

  if kill -0 "$pid" 2>/dev/null; then
    echo "FastAPI is running. pid=${pid}"
    echo "Bind: ${HOST}:${PORT}"
    echo "Log: ${LOG_FILE}"
    return 0
  fi

  echo "FastAPI is stopped. Stale pid file: ${PID_FILE}"
  return 3
}

show_logs() {
  ensure_dirs
  touch "$LOG_FILE"
  tail -n "${LINES:-120}" -f "$LOG_FILE"
}

case "${1:-}" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  logs)
    show_logs
    ;;
  -h|--help|help|"")
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
