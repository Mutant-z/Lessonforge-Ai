#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

remove_stale_pid "$BACKEND_PID_FILE"
remove_stale_pid "$FRONTEND_PID_FILE"

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  if ! command -v python3.11 >/dev/null 2>&1; then
    echo "错误：未找到 Python 3.11。请先安装 Python 3.11+。" >&2
    exit 1
  fi
  echo "首次启动：正在创建 Python 虚拟环境…"
  python3.11 -m venv "$PROJECT_DIR/.venv"
fi

if ! "$PROJECT_DIR/.venv/bin/python" -c "import app, fastapi" >/dev/null 2>&1; then
  echo "首次启动：正在安装后端依赖…"
  "$PROJECT_DIR/.venv/bin/pip" install -e "$PROJECT_DIR/backend[dev]"
fi

if [ ! -x "$PROJECT_DIR/frontend/node_modules/.bin/vite" ]; then
  echo "首次启动：正在安装前端依赖…"
  (cd "$PROJECT_DIR/frontend" && npm install)
fi

"$PROJECT_DIR/scripts/init_db.sh"

if is_running "$BACKEND_PID_FILE"; then
  echo "后端已在运行（PID $(read_pid "$BACKEND_PID_FILE")）"
else
  assert_port_available "后端" 8000
  echo "正在启动后端…"
  (
    cd "$PROJECT_DIR/backend"
    nohup "$PROJECT_DIR/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 >> "$BACKEND_LOG" 2>&1 &
    printf '%s\n' "$!" > "$BACKEND_PID_FILE"
  )
fi

if is_running "$FRONTEND_PID_FILE"; then
  echo "前端已在运行（PID $(read_pid "$FRONTEND_PID_FILE")）"
else
  assert_port_available "前端" 5173
  echo "正在启动前端…"
  (
    cd "$PROJECT_DIR/frontend"
    nohup "$PROJECT_DIR/frontend/node_modules/.bin/vite" --host 0.0.0.0 --port 5173 >> "$FRONTEND_LOG" 2>&1 &
    printf '%s\n' "$!" > "$FRONTEND_PID_FILE"
  )
fi

sleep 1

if ! is_running "$BACKEND_PID_FILE"; then
  echo "后端启动失败，请运行 ./scripts/logs.sh backend 查看日志。" >&2
  exit 1
fi
if ! is_running "$FRONTEND_PID_FILE"; then
  echo "前端启动失败，请运行 ./scripts/logs.sh frontend 查看日志。" >&2
  exit 1
fi

echo "LessonForge AI 已启动"
echo "前端：http://localhost:5173"
echo "API：http://localhost:8000/docs"
echo "日志：./scripts/logs.sh"
