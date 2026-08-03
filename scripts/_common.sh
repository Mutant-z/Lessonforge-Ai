#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"

mkdir -p "$RUNTIME_DIR"

read_pid() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    local pid
    pid="$(tr -dc '0-9' < "$pid_file")"
    if [ -n "$pid" ]; then
      printf '%s' "$pid"
      return 0
    fi
  fi
  return 1
}

is_running() {
  local pid_file="$1"
  local pid
  pid="$(read_pid "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

remove_stale_pid() {
  local pid_file="$1"
  if [ -f "$pid_file" ] && ! is_running "$pid_file"; then
    unlink "$pid_file"
  fi
}

listener_pids() {
  local port="$1"
  command -v lsof >/dev/null 2>&1 || return 0
  { lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true; } | sort -u
}

process_belongs_to_project() {
  local pid="$1"
  local cwd command_line
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
  command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$cwd" in
    "$PROJECT_DIR"|"$PROJECT_DIR"/*) return 0 ;;
  esac
  case "$command_line" in
    *"$PROJECT_DIR"*) return 0 ;;
  esac
  return 1
}

stop_project_listeners() {
  local name="$1"
  local port="$2"
  local pid
  for pid in $(listener_pids "$port"); do
    if ! process_belongs_to_project "$pid"; then
      echo "警告：端口 ${port} 被其他程序占用（PID ${pid}），未自动关闭。" >&2
      continue
    fi
    echo "正在关闭未登记的${name}进程（PID ${pid}，端口 ${port}）…"
    kill -TERM "$pid" 2>/dev/null || true
    local attempt=0
    while kill -0 "$pid" 2>/dev/null && [ "$attempt" -lt 20 ]; do
      sleep 0.25
      attempt=$((attempt + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "${name}进程未能及时退出，正在强制结束。"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
}

assert_port_available() {
  local name="$1"
  local port="$2"
  local pids
  pids="$(listener_pids "$port" | tr '\n' ' ')"
  if [ -n "$pids" ]; then
    echo "错误：${name}端口 ${port} 已被占用（PID ${pids% }）。请先运行 ./scripts/stop.sh 或检查占用程序。" >&2
    return 1
  fi
}
