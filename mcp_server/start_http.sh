#!/bin/bash
# Khởi động MCP server HTTP + ngrok để dùng làm claude.ai connector
#
# Yêu cầu: ngrok đã cài (https://ngrok.com/download) và đã auth (ngrok config add-authtoken <token>)
#
# Dùng:
#   chmod +x mcp_server/start_http.sh
#   ./mcp_server/start_http.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
PORT=8765

echo "🔌 Starting MCP HTTP server on port $PORT..."
cd "$PROJECT_DIR"
"$VENV_PYTHON" -m mcp_server.server --http --port "$PORT" &
SERVER_PID=$!

sleep 2

echo "🌍 Starting ngrok tunnel..."
ngrok http "$PORT" --host-header="localhost:$PORT" --log=stdout &
NGROK_PID=$!

sleep 3

# Lấy URL từ ngrok API
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys, json
data = json.load(sys.stdin)
tunnels = data.get('tunnels', [])
https = [t for t in tunnels if t['proto'] == 'https']
print(https[0]['public_url'] if https else '')
" 2>/dev/null)

if [ -n "$NGROK_URL" ]; then
    echo ""
    echo "✅ MCP Server sẵn sàng!"
    echo ""
    echo "Thêm vào claude.ai → Settings → Integrations → Add MCP Server:"
    echo ""
    echo "   URL: $NGROK_URL/mcp"
    echo ""
else
    echo "⚠️  Không lấy được ngrok URL. Kiểm tra http://localhost:4040"
    echo "   URL thủ công: https://<ngrok-id>.ngrok-free.app/mcp"
fi

echo "Nhấn Ctrl+C để dừng..."
wait $SERVER_PID
