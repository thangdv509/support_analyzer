"""
CRUD helpers for the sumtag collection.

Each document represents one Crisp session with all its segments,
each segment containing AI-generated topic tags and a bullet-point summary.

Schema:
{
    session_id:    str,          (Crisp session ID — unique index)
    website_id:    str,
    state:         str,
    crawl_date:    str,          (last date this session was crawled/updated)
    start_session: str | None,
    end_session:   str | None,   (updated when new segments are appended)
    msg_count:     int,
    segment_count: int,
    segments: [
        {
            segment:   int,
            msg_count: int | None,
            start:     str | None,
            end:       str | None,
            tags:      list[str],
            summary:   str,
        }
    ],
    created_at:    datetime,
    updated_at:    datetime,
}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection

from .connection import get_db

_COLLECTION = "sumtag"


def _col() -> Collection:
    col = get_db()[_COLLECTION]
    col.create_index([("session_id", ASCENDING)], unique=True, background=True)
    col.create_index([("crawl_date", ASCENDING)], background=True)
    return col


def _now() -> datetime:
    return datetime.now(timezone.utc)


def upsert_session(doc: dict[str, Any]) -> str:
    """
    Insert or replace a full session document (for bulk import).
    Returns 'inserted' or 'replaced'.
    """
    col = _col()
    session_id = doc["session_id"]
    existing = col.find_one({"session_id": session_id}, {"created_at": 1})

    now = _now()
    save_doc = {**doc, "updated_at": now}
    save_doc["created_at"] = existing["created_at"] if existing else now

    result = col.replace_one({"session_id": session_id}, save_doc, upsert=True)
    return "replaced" if result.matched_count else "inserted"


def append_segment(
    session_id: str,
    segment_data: dict[str, Any],
    crawl_date: str,
    website_id: str | None = None,
    state: str | None = None,
    start_session: str | None = None,
    end_session: str | None = None,
    msg_count: int | None = None,
) -> str:
    """
    Append a new segment to an existing session, or create a new session.

    segment_data must contain: {summary, tags} and optionally {start, end, msg_count}

    Returns 'appended', 'created', or 'skipped' (duplicate start time).
    """
    col = _col()
    existing = col.find_one({"session_id": session_id})
    now = _now()

    if existing:
        seg_start = segment_data.get("start")
        existing_segments = existing.get("segments", [])

        # Dedup by segment start time
        if seg_start and any(s.get("start") == seg_start for s in existing_segments):
            return "skipped"

        next_idx = len(existing_segments) + 1
        new_seg = {**segment_data, "segment": next_idx}

        update_fields: dict[str, Any] = {
            "crawl_date":    crawl_date,
            "segment_count": next_idx,
            "updated_at":    now,
        }
        if end_session:
            update_fields["end_session"] = end_session
        if state:
            update_fields["state"] = state
        if msg_count is not None:
            update_fields["msg_count"] = msg_count

        col.update_one(
            {"session_id": session_id},
            {"$push": {"segments": new_seg}, "$set": update_fields},
        )
        return "appended"
    else:
        segment_with_idx = {**segment_data, "segment": 1}
        doc = {
            "session_id":    session_id,
            "website_id":    website_id or "unknown",
            "state":         state or "unknown",
            "crawl_date":    crawl_date,
            "start_session": start_session,
            "end_session":   end_session,
            "msg_count":     msg_count or 0,
            "segment_count": 1,
            "segments":      [segment_with_idx],
            "created_at":    now,
            "updated_at":    now,
        }
        col.insert_one(doc)
        return "created"


def get_session(session_id: str) -> dict[str, Any] | None:
    return _col().find_one({"session_id": session_id})


def session_exists(session_id: str) -> bool:
    return _col().count_documents({"session_id": session_id}, limit=1) > 0
