"""
CRUD helpers for per-app grading collections.

Collections:
    grading_deco       — DECO app
    grading_searchpie  — SearchPie app

Unknown / unrecognized app → skipped (not saved).

Primary key: (session_id, date) — same session on different dates saves separately.
uuid: deterministic UUID5 from (session_id, date) — stable cross-reference key.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, ReplaceOne
from pymongo.collection import Collection

from .connection import get_db

_NS = uuid.UUID("c4f7a2e1-3b8d-5f0a-9e6c-2d1b4a7f8e3c")

ALL_GRADING_COLLECTIONS = ["grading_deco", "grading_searchpie"]


def _collection_name(app: str | None) -> str | None:
    if not app:
        return None
    u = app.upper()
    if "DECO" in u:
        return "grading_deco"
    if "SEARCHPIE" in u or "SEARCH PIE" in u:
        return "grading_searchpie"
    return None


def record_uuid(session_id: str, date: str) -> str:
    """Deterministic UUID5 from (session_id, date)."""
    return str(uuid.uuid5(_NS, f"{session_id}:{date}"))


def _col(app: str | None) -> Collection | None:
    name = _collection_name(app)
    if name is None:
        return None
    col = get_db()[name]
    col.create_index([("session_id", ASCENDING), ("date", ASCENDING)], unique=True, background=True)
    col.create_index([("uuid", ASCENDING)], unique=True, sparse=True, background=True)
    col.create_index([("session_id", ASCENDING)], background=True)
    col.create_index([("date", ASCENDING)], background=True)
    col.create_index([("primary_operator", ASCENDING)], background=True)
    return col


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
    shop_domain: str | None = None,
) -> dict[str, Any]:
    now = _now()
    return {
        "uuid":             record_uuid(session_id, date),
        "session_id":       session_id,
        "date":             date,
        "website_id":       website_id,
        "app":              app,
        "customer":         customer,
        "primary_operator": primary_operator,
        "is_resolved":      is_resolved,
        "transcript":       transcript,
        "summary":          summary,
        "tags":             tags,
        "grading":          grading,
        "crisp_url":        crisp_url,
        "shop_domain":      shop_domain,
        "ts":               created_at or now,
        "created_at":       created_at or now,
        "updated_at":       now,
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

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
    shop_domain: str | None = None,
) -> str:
    """Insert or replace. Returns 'inserted', 'replaced', or 'skipped' (unknown app)."""
    col = _col(app)
    if col is None:
        return "skipped"
    existing = col.find_one({"session_id": session_id, "date": date}, {"created_at": 1})
    doc = _build_doc(
        session_id, website_id, date, app, customer,
        primary_operator, is_resolved, transcript, grading,
        summary, tags, crisp_url,
        existing["created_at"] if existing else None,
        shop_domain,
    )
    result = col.replace_one({"session_id": session_id, "date": date}, doc, upsert=True)
    return "replaced" if result.matched_count else "inserted"


def upsert_many(records: list[dict[str, Any]]) -> dict[str, int]:
    """Bulk upsert grouped by app → collection. Skips unknown apps."""
    if not records:
        return {"inserted": 0, "replaced": 0}

    by_col: dict[str, list[dict]] = {}
    for r in records:
        name = _collection_name(r.get("app"))
        if name:
            by_col.setdefault(name, []).append(r)

    db = get_db()
    total_inserted = total_replaced = 0

    for col_name, col_records in by_col.items():
        col = db[col_name]
        col.create_index([("session_id", ASCENDING), ("date", ASCENDING)], unique=True, background=True)
        col.create_index([("uuid", ASCENDING)], unique=True, sparse=True, background=True)

        session_ids = [r["session_id"] for r in col_records]
        existing = {
            (doc["session_id"], doc["date"]): doc["created_at"]
            for doc in col.find(
                {"session_id": {"$in": session_ids}},
                {"session_id": 1, "date": 1, "created_at": 1},
            )
        }

        ops = []
        inserted = replaced = 0
        for r in col_records:
            sid, date = r["session_id"], r["date"]
            key = (sid, date)
            doc = _build_doc(
                sid, r["website_id"], date, r["app"], r["customer"],
                r["primary_operator"], r["is_resolved"], r["transcript"], r["grading"],
                r.get("summary"), r.get("tags"), r.get("crisp_url"), existing.get(key),
                r.get("shop_domain"),
            )
            ops.append(ReplaceOne({"session_id": sid, "date": date}, doc, upsert=True))
            if key in existing:
                replaced += 1
            else:
                inserted += 1

        col.bulk_write(ops, ordered=False)
        total_inserted += inserted
        total_replaced += replaced

    return {"inserted": total_inserted, "replaced": total_replaced}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_all_saved_keys() -> set[tuple[str, str]]:
    """Return all (session_id, date) pairs across all grading collections."""
    db = get_db()
    keys: set[tuple[str, str]] = set()
    for name in ALL_GRADING_COLLECTIONS:
        for doc in db[name].find({}, {"session_id": 1, "date": 1}):
            keys.add((doc["session_id"], doc["date"]))
    return keys


def get_chats_by_date(date: str, app: str | None = None) -> list[dict[str, Any]]:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_GRADING_COLLECTIONS
    return [doc for n in names if n for doc in db[n].find({"date": date})]


def get_chats_by_date_range(
    from_date: str,
    to_date: str,
    operator: str | None = None,
    app: str | None = None,
) -> list[dict[str, Any]]:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_GRADING_COLLECTIONS
    query: dict[str, Any] = {"date": {"$gte": from_date, "$lte": to_date}}
    if operator:
        query["primary_operator"] = operator
    return [
        doc
        for n in names if n
        for doc in db[n].find(query).sort("date", ASCENDING)
    ]


def get_chat(session_id: str, app: str | None = None) -> dict[str, Any] | None:
    """Fetch a single document by session_id, searching all collections if app not given."""
    db = get_db()
    names = [_collection_name(app)] if app else ALL_GRADING_COLLECTIONS
    for name in names:
        if name:
            doc = db[name].find_one({"session_id": session_id})
            if doc:
                return doc
    return None


def get_chats_by_operator(operator: str, date: str | None = None, app: str | None = None) -> list[dict[str, Any]]:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_GRADING_COLLECTIONS
    query: dict[str, Any] = {"primary_operator": operator}
    if date:
        query["date"] = date
    return [doc for n in names if n for doc in db[n].find(query)]


def session_exists(session_id: str, date: str | None = None, app: str | None = None) -> bool:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_GRADING_COLLECTIONS
    query: dict[str, Any] = {"session_id": session_id}
    if date:
        query["date"] = date
    return any(db[n].count_documents(query, limit=1) > 0 for n in names if n)
