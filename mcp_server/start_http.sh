#!/bin/bash
# Khởi động MCP server HTTP để dùng làm claude.ai connector
#
# Yêu cầu: PUBLIC_URL đã set trong .env (trỏ vào domain thật của bạn)
#
# Dùng:
#   chmod +x mcp_server/start_http.sh
#   ./mcp_server/start_http.sh [--port 8765]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
PORT=8765

# Parse --port flag
for arg in "$@"; do
  if [[ "$arg" =~ ^--port=([0-9]+)$ ]]; then
    PORT="${BASH_REMATCH[1]}"
  fi
done

# Load PUBLIC_URL from .env
if [ -f "$PROJECT_DIR/.env" ]; then
  export $(grep -E '^PUBLIC_URL=' "$PROJECT_DIR/.env" | xargs) 2>/dev/null || true
fi

PUBLIC_URL="${PUBLIC_URL:-http://localhost:$PORT}"

echo "🔌 Starting MCP HTTP server on port $PORT..."
echo "🌐 Public URL: $PUBLIC_URL"
echo ""
echo "Thêm vào claude.ai → Settings → Integrations → Add MCP Server:"
echo ""
echo "   URL: $PUBLIC_URL/mcp"
echo ""
echo "Nhấn Ctrl+C để dừng..."

cd "$PROJECT_DIR"
"$VENV_PYTHON" -m mcp_server.server --http --port "$PORT"
