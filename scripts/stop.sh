#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

stop_service() {
  local name="$1"
  local pid_file="$2"
  local launch_label="$3"

  # Removing the launchd job first is essential: killing only its current PID
  # makes launchd immediately start a replacement process.
  if launchd_service_exists "$launch_label"; then
    echo "正在关闭由 launchd 托管的${name}…"
    remove_launchd_service "$launch_label"
  fi

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

stop_service "前端" "$FRONTEND_PID_FILE" "$FRONTEND_LAUNCH_LABEL"
stop_service "后端" "$BACKEND_PID_FILE" "$BACKEND_LAUNCH_LABEL"

# Recover processes started manually or left behind after a stale/missing PID
# file. Only listeners that can be proven to belong to this project are stopped.
stop_project_listeners "前端" "$FRONTEND_PORT"
stop_project_listeners "后端" "$BACKEND_PORT"
