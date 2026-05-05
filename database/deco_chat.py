"""
CRUD helpers for the deco_chat collection.

Schema of each document:
{
    session_id:        str   (Crisp session ID)
    website_id:        str
    date:              str   (YYYY-MM-DD — ngày chấm)
    app:               str   ("DECO" | "SearchPie" | ...)
    customer:          str
    primary_operator:  str
    is_resolved:       bool
    transcript:        str
    summary:           str | None  (bullet-point summary)
    tags:              list[str] | None  (3 short topic labels from the same LLM call as summary)
    grading: {
        criteria: {
            <criterion>: { score: float, justification: str }
            ...
        }
        overall_summary:  str
        total_score_20:   float
        final_score_10:   float
    }
    crisp_url:         str | None
    ts:                datetime   (timestamp when first saved)
    created_at:        datetime
    updated_at:        datetime
}

Primary key: (session_id, date) — cho phép cùng session được chấm lại vào ngày khác
(khách quay lại chat tiếp). Trong cùng một ngày, không chấm lại.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, ReplaceOne
from pymongo.collection import Collection

from .connection import get_db

_COLLECTION = "deco_chat"


def _col() -> Collection:
    col = get_db()[_COLLECTION]
    # Migration: drop cũ unique index trên session_id đơn lẻ nếu còn tồn tại
    try:
        col.drop_index("session_id_1")
    except Exception:
        pass
    col.create_index([("session_id", ASCENDING), ("date", ASCENDING)], unique=True, background=True)
    col.create_index([("session_id", ASCENDING)], background=True)
    col.create_index([("date", ASCENDING)], background=True)
    col.create_index([("primary_operator", ASCENDING)], background=True)
    return col


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_doc(
    session_id: str,
    website_id: str,
    date: str,
    app: str,
    customer: str,
    primary_operator: str,
    is_resolved: bool,
    transcript: str,
    grading: dict[str, Any],
    summary: str | None = None,
    tags: list[str] | None = None,
    crisp_url: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now()
    return {
        "session_id":       session_id,
        "website_id":       website_id,
        "date":             date,
        "app":              app,
        "customer":         customer,
        "primary_operator": primary_operator,
        "is_resolved":      is_resolved,
        "transcript":       transcript,
        "summary":          summary,
        "tags":             tags,
        "grading":          grading,
        "crisp_url":        crisp_url,
        "ts":               created_at or now,
        "created_at":       created_at or now,
        "updated_at":       now,
    }


def upsert_chat(
    session_id: str,
    website_id: str,
    date: str,
    app: str,
    customer: str,
    primary_operator: str,
    is_resolved: bool,
    transcript: str,
    grading: dict[str, Any],
    summary: str | None = None,
    tags: list[str] | None = None,
    crisp_url: str | None = None,
) -> str:
    """
    Insert or replace a graded chat document by (session_id, date).
    Returns 'inserted' or 'replaced'.
    """
    col = _col()
    existing = col.find_one({"session_id": session_id, "date": date}, {"created_at": 1})
    created_at = existing["created_at"] if existing else None

    doc = _build_doc(
        session_id, website_id, date, app, customer,
        primary_operator, is_resolved, transcript, grading,
        summary, tags, crisp_url, created_at,
    )
    result = col.replace_one({"session_id": session_id, "date": date}, doc, upsert=True)
    return "replaced" if result.matched_count else "inserted"


def upsert_many(records: list[dict[str, Any]]) -> dict[str, int]:
    """
    Bulk upsert a list of graded chat dicts (same keys as upsert_chat args).
    Deduplication key: (session_id, date) — cùng session vào ngày khác vẫn được lưu.
    Returns {"inserted": N, "replaced": M}.
    """
    if not records:
        return {"inserted": 0, "replaced": 0}

    col = _col()
    session_ids = [r["session_id"] for r in records]
    # Lấy tất cả doc có session_id trùng (có thể nhiều date khác nhau)
    existing = {
        (doc["session_id"], doc["date"]): doc["created_at"]
        for doc in col.find(
            {"session_id": {"$in": session_ids}},
            {"session_id": 1, "date": 1, "created_at": 1},
        )
    }

    ops = []
    inserted = replaced = 0
    for r in records:
        sid, date = r["session_id"], r["date"]
        key = (sid, date)
        doc = _build_doc(
            sid, r["website_id"], date, r["app"], r["customer"],
            r["primary_operator"], r["is_resolved"], r["transcript"], r["grading"],
            r.get("summary"), r.get("tags"), r.get("crisp_url"), existing.get(key),
        )
        ops.append(ReplaceOne({"session_id": sid, "date": date}, doc, upsert=True))
        if key in existing:
            replaced += 1
        else:
            inserted += 1

    col.bulk_write(ops, ordered=False)
    return {"inserted": inserted, "replaced": replaced}


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_chat(session_id: str) -> dict[str, Any] | None:
    """Fetch a single document by session_id."""
    return _col().find_one({"session_id": session_id})


def get_chats_by_date(date: str) -> list[dict[str, Any]]:
    """Return all graded chats for a given date (YYYY-MM-DD)."""
    return list(_col().find({"date": date}))


def get_chats_by_operator(operator: str, date: str | None = None) -> list[dict[str, Any]]:
    """Return all chats for an operator, optionally filtered by date."""
    query: dict[str, Any] = {"primary_operator": operator}
    if date:
        query["date"] = date
    return list(_col().find(query))


def get_chats_by_date_range(
    from_date: str,
    to_date: str,
    operator: str | None = None,
    app: str | None = None,
) -> list[dict[str, Any]]:
    """
    Return chats where from_date <= date <= to_date.
    Optionally filter by operator and/or app.
    """
    query: dict[str, Any] = {"date": {"$gte": from_date, "$lte": to_date}}
    if operator:
        query["primary_operator"] = operator
    if app:
        query["app"] = app
    return list(_col().find(query).sort("date", ASCENDING))


def session_exists(session_id: str, date: str | None = None) -> bool:
    """Check if a (session_id, date) pair has already been graded and stored.
    If date is None, returns True if any graded entry exists for this session."""
    query: dict[str, Any] = {"session_id": session_id}
    if date:
        query["date"] = date
    return _col().count_documents(query, limit=1) > 0
