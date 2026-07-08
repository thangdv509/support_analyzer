"""Wrapper mỏng quanh crisp_api SDK, chỉ để gửi tin nhắn trả lời."""
import os
from crisp_api import Crisp
from dotenv import load_dotenv

load_dotenv()

IDENTIFIER = os.getenv("CRISP_IDENTIFIER")
KEY = os.getenv("CRISP_KEY")

_client = None


def get_client() -> Crisp:
    global _client
    if _client is None:
        _client = Crisp()
        _client.set_tier("plugin")
        _client.authenticate(IDENTIFIER, KEY)
    return _client


def send_text_reply(website_id: str, session_id: str, text: str) -> None:
    client = get_client()
    client.website.send_message_in_conversation(
        website_id,
        session_id,
        {
            "type": "text",
            "from": "operator",
            "origin": "chat",
            "content": text,
        },
    )
