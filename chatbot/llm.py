"""Sinh câu trả lời bằng OpenRouter — tái dùng pattern gọi API từ analyzer_v2.py."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

# TODO: sau khi test ổn, đổi sang lấy prompt từ database/prompts.py để quản lý version
# giống hệ thống QA grading, thay vì hardcode ở đây.
SYSTEM_PROMPT = """Bạn là trợ lý hỗ trợ khách hàng của PieLab (Shopify app).
Trả lời ngắn gọn, thân thiện, đúng trọng tâm câu hỏi của khách.
Nếu không chắc chắn về thông tin (giá, tính năng cụ thể, lỗi kỹ thuật phức tạp), hãy nói sẽ chuyển cho nhân viên hỗ trợ thay vì đoán bừa.
Không bịa thông tin về app hoặc chính sách."""


def generate_reply(user_message: str) -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Missing OPENROUTER_API_KEY in .env")

    response = requests.post(
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": 500,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
