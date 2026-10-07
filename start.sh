#!/usr/bin/env bash
# Start H3 Canvas on the laptop.
#   ./start.sh                         use the ComfyUI URL saved in Settings
#   ./start.sh --comfy http://home-pc:8188
#   ./start.sh --demo                  fake ComfyUI, separate demo data; never touches the PC
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10+ is required (brew install python)" >&2; exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js is required to build the UI (brew install node)" >&2; exit 1
fi

if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
if [ ! -f .venv/.deps-ok ] || [ backend/requirements.txt -nt .venv/.deps-ok ]; then
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r backend/requirements.txt
  touch .venv/.deps-ok
fi

if [ ! -f frontend/dist/index.html ] || \
   [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi

cd backend
if [ "${1:-}" = "--demo" ]; then
  shift
  ../.venv/bin/python -m h3canvas.mock_comfy --port 8189 >/dev/null 2>&1 &
  MOCK_PID=$!
  trap 'kill $MOCK_PID 2>/dev/null' EXIT
  echo "Demo mode: fake ComfyUI on :8189, data in ~/H3Canvas-demo"
  ../.venv/bin/python -m h3canvas --comfy http://127.0.0.1:8189 --data ~/H3Canvas-demo "$@"
else
  ../.venv/bin/python -m h3canvas "$@"
fi
