"""
Prompt versioning for the QA grading criteria.

Collection: prompts
Schema:
{
    version:    int        (auto-increment, 1-based)
    content:    str        (full GRADING_CRITERIA text)
    reason:     str        (why it was changed)
    is_active:  bool       (only one active at a time)
    created_at: datetime
}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from .connection import get_db

_COLLECTION = "prompts"


def _col():
    col = get_db()[_COLLECTION]
    col.create_index([("version", DESCENDING)], background=True)
    col.create_index([("is_active", ASCENDING)], background=True)
    return col


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_active_prompt() -> dict[str, Any] | None:
    """Return the currently active prompt document, or None if none saved yet."""
    return _col().find_one({"is_active": True})


def get_prompt_content() -> str | None:
    """Return just the content string of the active prompt."""
    doc = get_active_prompt()
    return doc["content"] if doc else None


def save_prompt(content: str, reason: str = "") -> dict[str, Any]:
    """
    Save a new prompt version, deactivate the previous one.
    Returns the new document.
    """
    col = _col()
    col.update_many({"is_active": True}, {"$set": {"is_active": False}})

    last = col.find_one(sort=[("version", DESCENDING)])
    version = (last["version"] + 1) if last else 1

    doc = {
        "version":    version,
        "content":    content,
        "reason":     reason,
        "is_active":  True,
        "created_at": _now(),
    }
    col.insert_one(doc)
    doc["_id"] = str(doc["_id"])
    return doc


def list_prompt_versions() -> list[dict[str, Any]]:
    """Return all prompt versions (newest first), without the full content."""
    return [
        {**{k: v for k, v in d.items() if k not in ("content", "_id")}, "_id": str(d["_id"])}
        for d in _col().find({}, sort=[("version", DESCENDING)])
    ]
