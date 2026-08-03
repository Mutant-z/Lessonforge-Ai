#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

stop_service() {
  local name="$1"
  local pid_file="$2"

  if ! is_running "$pid_file"; then
    remove_stale_pid "$pid_file"
    echo "$name 未运行"
    return 0
  fi

  local pid
  pid="$(read_pid "$pid_file")"
  echo "正在关闭${name}（PID ${pid}）…"
  kill -TERM "$pid" 2>/dev/null || true

  local attempt=0
  while kill -0 "$pid" 2>/dev/null && [ "$attempt" -lt 20 ]; do
    sleep 0.5
    attempt=$((attempt + 1))
  done

  if kill -0 "$pid" 2>/dev/null; then
    echo "${name} 未能及时退出，正在强制结束。"
    kill -KILL "$pid" 2>/dev/null || true
  fi
  unlink "$pid_file" 2>/dev/null || true
  echo "${name} 已关闭"
}

stop_service "前端" "$FRONTEND_PID_FILE"
stop_service "后端" "$BACKEND_PID_FILE"

# Recover processes started manually or left behind after a stale/missing PID
# file. Only listeners that can be proven to belong to this project are stopped.
stop_project_listeners "前端" 5173
stop_project_listeners "后端" 8000
