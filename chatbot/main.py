"""
Chatbot cơ bản: nhận webhook Crisp -> sinh reply bằng LLM -> gửi lại qua Crisp API.

Chạy:
    uvicorn chatbot.main:app --port 8091 --reload
(chạy từ thư mục gốc project để load được .env)

Để mở cổng public qua ngrok (test với Crisp thật trên server), dùng:
    ./chatbot/start_ngrok.sh
"""
import os
import json
import hmac
import hashlib
import logging

from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv

from chatbot.llm import generate_reply
from chatbot.crisp_client import send_text_reply

load_dotenv()

CRISP_WEBHOOK_SECRET = os.getenv("CRISP_WEBHOOK_SECRET")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("chatbot")

app = FastAPI(title="Crisp Chatbot (basic)")


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not CRISP_WEBHOOK_SECRET:
        return True
    if not signature_header:
        return False
    expected = hmac.new(CRISP_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def handle_message(website_id: str, session_id: str, content: str):
    try:
        reply = generate_reply(content)
        send_text_reply(website_id, session_id, reply)
        logger.info(f"[{session_id}] replied: {reply[:120]}")
    except Exception:
        logger.exception(f"[{session_id}] failed to generate/send reply")


@app.get("/")
def health():
    return {"ok": True, "service": "crisp-chatbot"}


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    signature = request.headers.get("x-crisp-signature")

    if not verify_signature(raw_body, signature):
        logger.warning("Invalid webhook signature, ignoring event")
        return {"ok": True}

    payload = json.loads(raw_body)
    event = payload.get("event")
    data = payload.get("data", {})

    # Chỉ xử lý tin nhắn text do khách gửi. Bỏ qua tin của operator/bot
    # (kể cả tin bot vừa gửi ra) để tránh vòng lặp tự trả lời chính mình.
    if event != "message:send" or data.get("from") != "user" or data.get("type") != "text":
        return {"ok": True}

    website_id = payload.get("website_id")
    session_id = data.get("session_id")
    content = data.get("content")

    if not (website_id and session_id and content):
        logger.warning(f"Missing fields in payload: {payload}")
        return {"ok": True}

    # Trả 200 ngay, xử lý LLM + gửi reply ở background để không bị Crisp timeout/retry
    background_tasks.add_task(handle_message, website_id, session_id, content)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("CHATBOT_PORT", "8091"))
    uvicorn.run(app, host="0.0.0.0", port=port)
