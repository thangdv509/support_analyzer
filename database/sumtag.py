"""
CRUD helpers for per-app sumtag collections.

Collections:
    sumtag_deco       — DECO app
    sumtag_searchpie  — SearchPie app

Unknown / unrecognized app → skipped.
Primary key: (session_id, date) — mirrors grading collections.
uuid: deterministic UUID5 from (session_id, date).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, ReplaceOne
from pymongo.collection import Collection

from .connection import get_db

_NS = uuid.UUID("d5e8b3f2-4c9a-6e1b-0f7d-3a2c5b8e9f4d")

ALL_SUMTAG_COLLECTIONS = ["sumtag_deco", "sumtag_searchpie"]


def _collection_name(app: str | None) -> str | None:
    if not app:
        return None
    u = app.upper()
    if "DECO" in u:
        return "sumtag_deco"
    if "SEARCHPIE" in u or "SEARCH PIE" in u:
        return "sumtag_searchpie"
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
    col.create_index([("date", ASCENDING)], background=True)
    return col


def _now() -> datetime:
    return datetime.now(timezone.utc)


def upsert(
    session_id: str,
    date: str,
    tags: list[str],
    summary: str | None,
    app: str | None = None,
    website_id: str | None = None,
    primary_operator: str | None = None,
    start: str | None = None,
    end: str | None = None,
    msg_count: int | None = None,
) -> str:
    """Insert or replace. Returns 'inserted', 'replaced', or 'skipped' (unknown app)."""
    col = _col(app)
    if col is None:
        return "skipped"
    existing = col.find_one({"session_id": session_id, "date": date}, {"created_at": 1})
    now = _now()
    doc = {
        "uuid":             record_uuid(session_id, date),
        "session_id":       session_id,
        "date":             date,
        "website_id":       website_id or "unknown",
        "app":              app,
        "primary_operator": primary_operator,
        "start":            start,
        "end":              end,
        "msg_count":        msg_count,
        "tags":             tags,
        "summary":          summary,
        "created_at":       existing["created_at"] if existing else now,
        "updated_at":       now,
    }
    result = col.replace_one({"session_id": session_id, "date": date}, doc, upsert=True)
    return "replaced" if result.matched_count else "inserted"


def upsert_many(records: list[dict[str, Any]]) -> dict[str, int]:
    """Bulk upsert grouped by app. Skips unknown apps."""
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

        keys = [(r["session_id"], r["date"]) for r in col_records]
        existing = {
            (doc["session_id"], doc["date"]): doc["created_at"]
            for doc in col.find(
                {"$or": [{"session_id": s, "date": d} for s, d in keys]},
                {"session_id": 1, "date": 1, "created_at": 1},
            )
        }

        now = _now()
        ops = []
        inserted = replaced = 0
        for r in col_records:
            sid, date = r["session_id"], r["date"]
            key = (sid, date)
            doc = {
                "uuid":             record_uuid(sid, date),
                "session_id":       sid,
                "date":             date,
                "website_id":       r.get("website_id") or "unknown",
                "app":              r.get("app"),
                "primary_operator": r.get("primary_operator"),
                "start":            r.get("start"),
                "end":              r.get("end"),
                "msg_count":        r.get("msg_count"),
                "tags":             r.get("tags", []),
                "summary":          r.get("summary"),
                "created_at":       existing.get(key, now),
                "updated_at":       now,
            }
            ops.append(ReplaceOne({"session_id": sid, "date": date}, doc, upsert=True))
            if key in existing:
                replaced += 1
            else:
                inserted += 1

        col.bulk_write(ops, ordered=False)
        total_inserted += inserted
        total_replaced += replaced

    return {"inserted": total_inserted, "replaced": total_replaced}


def exists(session_id: str, date: str, app: str | None = None) -> bool:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_SUMTAG_COLLECTIONS
    query = {"session_id": session_id, "date": date}
    return any(db[n].count_documents(query, limit=1) > 0 for n in names if n)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_by_date(date: str, app: str | None = None) -> list[dict[str, Any]]:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_SUMTAG_COLLECTIONS
    return [doc for n in names if n for doc in db[n].find({"date": date})]


def get_by_date_range(
    from_date: str,
    to_date: str,
    operator: str | None = None,
    app: str | None = None,
) -> list[dict[str, Any]]:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_SUMTAG_COLLECTIONS
    query: dict[str, Any] = {"date": {"$gte": from_date, "$lte": to_date}}
    if operator:
        query["primary_operator"] = operator
    return [
        doc
        for n in names if n
        for doc in db[n].find(query).sort("date", ASCENDING)
    ]


def get_by_session(session_id: str, app: str | None = None) -> dict[str, Any] | None:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_SUMTAG_COLLECTIONS
    for name in names:
        if name:
            doc = db[name].find_one({"session_id": session_id})
            if doc:
                return doc
    return None


def get_by_operator(operator: str, app: str | None = None) -> list[dict[str, Any]]:
    db = get_db()
    names = [_collection_name(app)] if app else ALL_SUMTAG_COLLECTIONS
    return [doc for n in names if n for doc in db[n].find({"primary_operator": operator})]
