#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$PROJECT_DIR/.runtime"
BACKEND_PID_FILE="$RUNTIME_DIR/backend.pid"
FRONTEND_PID_FILE="$RUNTIME_DIR/frontend.pid"
BACKEND_LOG="$RUNTIME_DIR/backend.log"
FRONTEND_LOG="$RUNTIME_DIR/frontend.log"
BACKEND_LAUNCH_LOG="$RUNTIME_DIR/backend-launchd.log"
FRONTEND_LAUNCH_LOG="$RUNTIME_DIR/frontend-launchd.log"

if [ -f "$PROJECT_DIR/.env" ]; then
  while IFS='=' read -r key value || [ -n "$key" ]; do
    # 忽略空行和注释行
    case "$key" in
      \#*|"") continue ;;
    esac
    key="$(echo "$key" | xargs)"
    # 仅当 key 为有效变量名时导出
    if [[ "$key" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
      # 去除首尾空格和包裹的引号
      value="$(echo "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^["'\''"]//' -e 's/["'\''"]$//')"
      export "$key"="$value"
    fi
  done < "$PROJECT_DIR/.env"
fi

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# `nohup ... &` is not enough in desktop/agent environments: the host may reap
# every process that still belongs to the completed command session.  On macOS
# we therefore submit the dev servers to the user's launchd domain.  Include a
# stable project-path checksum so multiple LessonForge checkouts do not collide.
PROJECT_LAUNCH_ID="$(printf '%s' "$PROJECT_DIR" | cksum | awk '{print $1}')"
BACKEND_LAUNCH_LABEL="com.lessonforge.ai.${PROJECT_LAUNCH_ID}.backend"
FRONTEND_LAUNCH_LABEL="com.lessonforge.ai.${PROJECT_LAUNCH_ID}.frontend"

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

launchd_available() {
  [ "$(uname -s)" = "Darwin" ] && command -v launchctl >/dev/null 2>&1
}

launchd_target() {
  local label="$1"
  printf 'gui/%s/%s' "$(id -u)" "$label"
}

launchd_service_exists() {
  local label="$1"
  launchd_available && launchctl print "$(launchd_target "$label")" >/dev/null 2>&1
}

launchd_service_pid() {
  local label="$1"
  launchd_available || return 1
  launchctl print "$(launchd_target "$label")" 2>/dev/null \
    | sed -n 's/^[[:space:]]*pid = \([0-9][0-9]*\)$/\1/p' \
    | head -n 1
}

remove_launchd_service() {
  local label="$1"
  if launchd_service_exists "$label"; then
    launchctl remove "$label" >/dev/null 2>&1 || true
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-80}"
  local attempt=0
  while [ "$attempt" -lt "$attempts" ]; do
    if curl --silent --show-error --fail --max-time 1 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
    attempt=$((attempt + 1))
  done
  echo "错误：${name}进程已启动，但 HTTP 就绪检查失败（${url}）。" >&2
  return 1
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
