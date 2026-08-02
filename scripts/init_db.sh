#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$PROJECT_DIR/storage/uploads" "$PROJECT_DIR/storage/generated" "$PROJECT_DIR/storage/temp"
cd "$PROJECT_DIR/backend"
"$PROJECT_DIR/.venv/bin/alembic" upgrade head

