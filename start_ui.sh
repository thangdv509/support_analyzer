#!/usr/bin/env bash
# Start QA Dashboard — FastAPI backend (port 8000) + React Vite dev server (port 5173)
#
# Usage:
#   ./start_ui.sh          — dev mode (both servers, hot-reload)
#   ./start_ui.sh --prod   — production mode (serve built static files via FastAPI only)
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load nvm if available ─────────────────────────────────────────────────────
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# ── Python venv ───────────────────────────────────────────────────────────────
if [ -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  source "$SCRIPT_DIR/venv/bin/activate"
fi

python -c "import fastapi" 2>/dev/null || pip install fastapi "uvicorn[standard]" --quiet

# ── Production mode ───────────────────────────────────────────────────────────
if [ "$1" = "--prod" ]; then
  echo "🏭 Production mode — building frontend first..."
  cd "$SCRIPT_DIR/ui"
  [ ! -d "node_modules" ] && npm install
  npm run build
  cd "$SCRIPT_DIR"
  echo "🚀 Serving on http://localhost:8000"
  uvicorn api.main:app --port 8000 --host 0.0.0.0
  exit 0
fi

# ── Dev mode (default) ────────────────────────────────────────────────────────
echo "🚀 Starting FastAPI backend   → http://localhost:8000"
echo "   API docs                   → http://localhost:8000/docs"
uvicorn api.main:app --reload --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!

echo ""
echo "🎨 Starting React dev server  → http://localhost:5173"
cd "$SCRIPT_DIR/ui"
[ ! -d "node_modules" ] && npm install
npm run dev

# Cleanup backend when Vite exits
kill "$BACKEND_PID" 2>/dev/null || true
