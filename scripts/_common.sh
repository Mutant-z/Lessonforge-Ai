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

