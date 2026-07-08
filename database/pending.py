"""
Pending chat sessions: LLM marked segment as "not complete".
Will be retried on subsequent daily runs (up to MAX_RETRIES times).
"""
from datetime import datetime, timezone
from pymongo import ASCENDING
from .connection import get_db

MAX_RETRIES = 3
_COL = "pending_chats"


def _col():
    col = get_db()[_COL]
    col.create_index([("session_id", ASCENDING)], unique=True, background=True)
    return col


def add(session_id: str, website_id: str, app: str, original_date: str) -> None:
    """Add session to pending (idempotent — won't overwrite existing)."""
    _col().update_one(
        {"session_id": session_id},
        {"$setOnInsert": {
            "session_id": session_id,
            "website_id": website_id,
            "app": app,
            "original_date": original_date,
            "retry_count": 0,
            "added_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


def get_all() -> list[dict]:
    return list(_col().find())


def remove(session_id: str) -> None:
    _col().delete_one({"session_id": session_id})


def increment_retry(session_id: str) -> int:
    """Increment retry_count. Returns new count."""
    result = _col().find_one_and_update(
        {"session_id": session_id},
        {"$inc": {"retry_count": 1}, "$set": {"last_checked": datetime.now(timezone.utc)}},
        return_document=True,
    )
    return result["retry_count"] if result else 0


def count() -> int:
    return _col().count_documents({})
