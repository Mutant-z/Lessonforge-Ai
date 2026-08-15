#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

TARGET="${1:-all}"
LINES="${LOG_LINES:-100}"
FOLLOW="${LOG_FOLLOW:-true}"

if ! [[ "$LINES" =~ ^[0-9]+$ ]]; then
  echo "错误：LOG_LINES 必须是非负整数。" >&2
  exit 1
fi

case "$TARGET" in
  backend)
    FILES=("$BACKEND_LAUNCH_LOG" "$BACKEND_LOG")
    ;;
  frontend)
    FILES=("$FRONTEND_LAUNCH_LOG" "$FRONTEND_LOG")
    ;;
  all)
    FILES=("$BACKEND_LAUNCH_LOG" "$FRONTEND_LAUNCH_LOG" "$BACKEND_LOG" "$FRONTEND_LOG")
    ;;
  *)
    echo "用法：$0 [all|backend|frontend]" >&2
    echo "可选环境变量：LOG_LINES=100 LOG_FOLLOW=true|false" >&2
    exit 1
    ;;
esac

EXISTING=()
for file in "${FILES[@]}"; do
  if [ -f "$file" ]; then
    EXISTING+=("$file")
  fi
done

if [ "${#EXISTING[@]}" -eq 0 ]; then
  echo "尚无日志。请先运行 ./scripts/start.sh。"
  exit 0
fi

if [ "$FOLLOW" = "false" ]; then
  tail -n "$LINES" "${EXISTING[@]}"
else
  echo "正在持续查看日志，按 Ctrl+C 退出。"
  tail -n "$LINES" -F "${EXISTING[@]}"
fi
