#!/usr/bin/env bash
# Start QA Dashboard
#
# Usage:
#   ./start_ui.sh            — dev mode (backend + Vite hot-reload)
#   ./start_ui.sh --prod     — production (build frontend, serve qua FastAPI)
#   ./start_ui.sh --prod --port 9000   — chỉ định port
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env ─────────────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -E '^(API_PORT|UI_PORT)=' "$SCRIPT_DIR/.env" | xargs) 2>/dev/null || true
fi

API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-5173}"

# ── Parse --port flag ─────────────────────────────────────────────────────────
for arg in "$@"; do
  if [[ "$arg" =~ ^--port=([0-9]+)$ ]]; then
    API_PORT="${BASH_REMATCH[1]}"
  fi
done

# ── Load nvm if available ─────────────────────────────────────────────────────
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# ── Python venv ───────────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  source "$SCRIPT_DIR/venv/bin/activate"
fi

python -c "import fastapi" 2>/dev/null || pip install fastapi "uvicorn[standard]" --quiet

# ── Production mode ───────────────────────────────────────────────────────────
if [[ "$*" == *"--prod"* ]]; then
  echo "🏭 Production mode"
  cd "$SCRIPT_DIR/ui"
  [ ! -d "node_modules" ] && npm install
  npm run build
  cd "$SCRIPT_DIR"
  echo "🚀 Serving on http://0.0.0.0:$API_PORT  (truy cập: http://<IP_SERVER>:$API_PORT)"
  uvicorn api.main:app --port "$API_PORT" --host 0.0.0.0
  exit 0
fi

# ── Dev mode ──────────────────────────────────────────────────────────────────
echo "🚀 FastAPI  → http://0.0.0.0:$API_PORT"
uvicorn api.main:app --reload --port "$API_PORT" --host 0.0.0.0 &
BACKEND_PID=$!

echo "🎨 Vite dev → http://0.0.0.0:$UI_PORT"
cd "$SCRIPT_DIR/ui"
[ ! -d "node_modules" ] && npm install
VITE_PORT=$UI_PORT npm run dev -- --host 0.0.0.0 --port "$UI_PORT"

kill "$BACKEND_PID" 2>/dev/null || true
