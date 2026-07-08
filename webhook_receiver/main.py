"""
Webhook receiver để test thử — chỉ nhận & log lại payload Crisp gửi tới.
Không xử lý logic gì, mục đích là xác nhận:
  1. Crisp có gọi được tới endpoint của mình không
  2. Payload/format event thực tế trông như thế nào (event type, data.from, content...)
  3. Chữ ký (signature) header Crisp gửi kèm có đúng như tài liệu không

Chạy:
    uvicorn webhook_receiver.main:app --port 8090 --reload
(chạy từ thư mục gốc project để load được .env)

Để mở cổng public qua ngrok (test với Crisp thật trên server), dùng:
    ./webhook_receiver/start_ngrok.sh
"""
import os
import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

CRISP_WEBHOOK_SECRET = os.getenv("CRISP_WEBHOOK_SECRET")  # optional, set khi đăng ký webhook trong Crisp
LOG_PATH = os.path.join(os.path.dirname(__file__), "events.log")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("webhook_receiver")

app = FastAPI(title="Crisp Webhook Receiver (test)")


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Crisp ký payload bằng HMAC-SHA256 với webhook secret, gửi kèm header X-Crisp-Signature."""
    if not CRISP_WEBHOOK_SECRET:
        return True  # chưa cấu hình secret -> bỏ qua verify, chỉ dùng lúc test local
    if not signature_header:
        return False
    expected = hmac.new(CRISP_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


@app.get("/")
def health():
    return {"ok": True, "service": "crisp-webhook-receiver"}


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-crisp-signature")

    valid = verify_signature(raw_body, signature)
    if not valid:
        logger.warning("Invalid signature — vẫn log payload để debug, nhưng đánh dấu untrusted")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        payload = {"_raw": raw_body.decode(errors="replace")}

    entry = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "signature_valid": valid,
        "event": payload.get("event"),
        "website_id": payload.get("website_id"),
        "data": payload.get("data"),
    }

    logger.info(json.dumps(entry, ensure_ascii=False, indent=2))
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Crisp yêu cầu trả 200 nhanh, không thì nó sẽ retry / disable webhook
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("WEBHOOK_PORT", "8090"))
    uvicorn.run(app, host="0.0.0.0", port=port)
