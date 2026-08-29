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

if ! (
  cd "$PROJECT_DIR/backend"
  "$PROJECT_DIR/.venv/bin/python" -c "import app, fastapi, imageio_ffmpeg, PIL, sqlalchemy"
) >/dev/null 2>&1; then
  echo "首次启动：正在安装后端依赖…"
  "$PROJECT_DIR/.venv/bin/pip" install -e "$PROJECT_DIR/backend[dev]"
fi

# Resolve the venv interpreter symlink before handing it to launchd.  The
# bundled Codex runtime marks the symlink itself with provenance metadata; macOS
# may reject that indirect executable with EX_CONFIG/EPERM even though the real
# interpreter is trusted.  PYTHONPATH keeps the venv's installed packages.
BACKEND_PYTHON="$("$PROJECT_DIR/.venv/bin/python" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
BACKEND_SITE_PACKAGES="$("$PROJECT_DIR/.venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"

if [ ! -x "$PROJECT_DIR/frontend/node_modules/.bin/vite" ]; then
  echo "首次启动：正在安装前端依赖…"
  (cd "$PROJECT_DIR/frontend" && npm install)
fi

"$PROJECT_DIR/scripts/init_db.sh"

if launchd_service_exists "$BACKEND_LAUNCH_LABEL" && backend_pid="$(launchd_service_pid "$BACKEND_LAUNCH_LABEL" || true)" && [ -n "$backend_pid" ]; then
  printf '%s\n' "$backend_pid" > "$BACKEND_PID_FILE"
  echo "后端已由 launchd 托管（PID ${backend_pid}）"
elif is_running "$BACKEND_PID_FILE"; then
  echo "后端已在运行（PID $(read_pid "$BACKEND_PID_FILE")）"
else
  assert_port_available "后端" "$BACKEND_PORT"
  echo "正在启动后端…"
  if launchd_available; then
    remove_launchd_service "$BACKEND_LAUNCH_LABEL"
    # ``launchctl submit`` does not reliably inherit proxy variables from the
    # invoking shell.  In fake-IP/enhanced proxy modes external hostnames may
    # resolve to 198.18.0.0/15 and are unreachable unless the backend uses the
    # local proxy.  Pass the already configured environment through explicitly.
    launchctl submit \
      -l "$BACKEND_LAUNCH_LABEL" \
      -o "$BACKEND_LAUNCH_LOG" \
      -e "$BACKEND_LAUNCH_LOG" \
      -- /bin/sh -c '
        cd "$1" || exit 1
        export PYTHONPATH="$2"
        export HTTP_PROXY="$6" HTTPS_PROXY="$7" ALL_PROXY="$8" NO_PROXY="$9"
        export http_proxy="${10}" https_proxy="${11}" all_proxy="${12}" no_proxy="${13}"
        exec "$3" -m uvicorn app.main:app --host "$4" --port "$5"
      ' lessonforge-backend \
      "$PROJECT_DIR/backend" "$BACKEND_SITE_PACKAGES" "$BACKEND_PYTHON" \
      "$BACKEND_HOST" "$BACKEND_PORT" \
      "${HTTP_PROXY:-}" "${HTTPS_PROXY:-}" "${ALL_PROXY:-}" "${NO_PROXY:-}" \
      "${http_proxy:-}" "${https_proxy:-}" "${all_proxy:-}" "${no_proxy:-}"
    backend_pid="$(launchd_service_pid "$BACKEND_LAUNCH_LABEL" || true)"
    [ -n "$backend_pid" ] && printf '%s\n' "$backend_pid" > "$BACKEND_PID_FILE"
  else
    (
      cd "$PROJECT_DIR/backend"
      nohup "$PROJECT_DIR/.venv/bin/uvicorn" app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" >> "$BACKEND_LOG" 2>&1 &
      printf '%s\n' "$!" > "$BACKEND_PID_FILE"
    )
  fi
fi

if launchd_service_exists "$FRONTEND_LAUNCH_LABEL" && frontend_pid="$(launchd_service_pid "$FRONTEND_LAUNCH_LABEL" || true)" && [ -n "$frontend_pid" ]; then
  printf '%s\n' "$frontend_pid" > "$FRONTEND_PID_FILE"
  echo "前端已由 launchd 托管（PID ${frontend_pid}）"
elif is_running "$FRONTEND_PID_FILE"; then
  echo "前端已在运行（PID $(read_pid "$FRONTEND_PID_FILE")）"
else
  assert_port_available "前端" "$FRONTEND_PORT"
  echo "正在启动前端…"
  if launchd_available; then
    remove_launchd_service "$FRONTEND_LAUNCH_LABEL"
    node_bin="$(command -v node)"
    launchctl submit \
      -l "$FRONTEND_LAUNCH_LABEL" \
      -o "$FRONTEND_LAUNCH_LOG" \
      -e "$FRONTEND_LAUNCH_LOG" \
      -- "$node_bin" "$PROJECT_DIR/frontend/node_modules/vite/bin/vite.js" "$PROJECT_DIR/frontend" --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
    frontend_pid="$(launchd_service_pid "$FRONTEND_LAUNCH_LABEL" || true)"
    [ -n "$frontend_pid" ] && printf '%s\n' "$frontend_pid" > "$FRONTEND_PID_FILE"
  else
    (
      cd "$PROJECT_DIR/frontend"
      nohup "$PROJECT_DIR/frontend/node_modules/.bin/vite" --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" >> "$FRONTEND_LOG" 2>&1 &
      printf '%s\n' "$!" > "$FRONTEND_PID_FILE"
    )
  fi
fi

if ! wait_for_http "后端" "http://127.0.0.1:${BACKEND_PORT}/health"; then
  remove_launchd_service "$BACKEND_LAUNCH_LABEL"
  echo "后端启动失败，请运行 ./scripts/logs.sh backend 查看日志。" >&2
  exit 1
fi
if ! wait_for_http "前端" "http://127.0.0.1:${FRONTEND_PORT}/"; then
  remove_launchd_service "$FRONTEND_LAUNCH_LABEL"
  remove_launchd_service "$BACKEND_LAUNCH_LABEL"
  echo "前端启动失败，请运行 ./scripts/logs.sh frontend 查看日志。" >&2
  exit 1
fi

echo "LessonForge AI 已启动"
echo "前端：http://localhost:${FRONTEND_PORT}"
echo "API：http://localhost:${BACKEND_PORT}/docs"
echo "日志：./scripts/logs.sh"
