#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  python3.11 -m venv "$PROJECT_DIR/.venv"
  "$PROJECT_DIR/.venv/bin/pip" install -e "$PROJECT_DIR/backend[dev]"
fi
(cd "$PROJECT_DIR/backend" && "$PROJECT_DIR/.venv/bin/uvicorn" app.main:app --reload --port 8000) &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT
cd "$PROJECT_DIR/frontend"
npm install
npm run dev

