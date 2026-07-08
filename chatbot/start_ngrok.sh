#!/bin/bash
# Khởi động chatbot + ngrok tunnel để mở cổng public trên server
# (theo đúng pattern ngrok cũ dùng ở mcp_server/start_http.sh trước khi đổi qua domain)
#
# Yêu cầu: ngrok đã cài (https://ngrok.com/download) và đã auth
#          (ngrok config add-authtoken <token>)
#
# Dùng:
#   chmod +x chatbot/start_ngrok.sh
#   ./chatbot/start_ngrok.sh [--port 8091]
#
# Nếu có domain ngrok cố định (reserved domain), set trong .env:
#   NGROK_DOMAIN=your-name.ngrok-free.app

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
PORT=8091

# Parse --port flag
for arg in "$@"; do
  if [[ "$arg" =~ ^--port=([0-9]+)$ ]]; then
    PORT="${BASH_REMATCH[1]}"
  fi
done

# Load NGROK_DOMAIN từ .env nếu có domain cố định
if [ -f "$PROJECT_DIR/.env" ]; then
  export $(grep -E '^NGROK_DOMAIN=' "$PROJECT_DIR/.env" | xargs) 2>/dev/null || true
fi

echo "🔌 Starting chatbot on port $PORT..."
cd "$PROJECT_DIR"
"$VENV_PYTHON" -m uvicorn chatbot.main:app --host 0.0.0.0 --port "$PORT" &
SERVER_PID=$!

sleep 2

echo "🌍 Starting ngrok tunnel..."
if [ -n "$NGROK_DOMAIN" ]; then
  ngrok http --url="$NGROK_DOMAIN" "$PORT" --log=stdout &
else
  ngrok http "$PORT" --log=stdout &
fi
NGROK_PID=$!

trap 'kill "$SERVER_PID" "$NGROK_PID" 2>/dev/null' EXIT

sleep 3

# Lấy URL từ ngrok local API
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys, json
data = json.load(sys.stdin)
tunnels = data.get('tunnels', [])
https = [t for t in tunnels if t['proto'] == 'https']
print(https[0]['public_url'] if https else '')
" 2>/dev/null)

if [ -n "$NGROK_URL" ]; then
    echo ""
    echo "✅ Chatbot sẵn sàng!"
    echo ""
    echo "Đăng ký URL này vào Crisp Dashboard → website → Settings → Plugins → Webhooks"
    echo "(chọn event 'message:send'):"
    echo ""
    echo "   URL: $NGROK_URL/webhook"
    echo ""
else
    echo "⚠️  Không lấy được ngrok URL. Kiểm tra http://localhost:4040"
    echo "   URL thủ công: https://<ngrok-id>.ngrok-free.app/webhook"
fi

echo "Nhấn Ctrl+C để dừng..."
wait $SERVER_PID
