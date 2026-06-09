"""
Change requests from support users for reviews they want to edit/delete.
Manager/admin must approve or reject.

Collection: qa_review_requests
"""
from __future__ import annotations

from datetime import datetime, timezone
from bson import ObjectId
from pymongo import DESCENDING

from .connection import get_db

_COL = "qa_review_requests"


def _col():
    col = get_db()[_COL]
    col.create_index([("status", 1)], background=True)
    col.create_index([("requested_by", 1)], background=True)
    return col


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


def create_request(review_id: str, action: str, changes: dict,
                   reason: str, requested_by: str) -> dict:
    """action: 'update' | 'delete'"""
    now = _now()
    doc = {
        "review_id":    review_id,
        "action":       action,          # 'update' | 'delete'
        "changes":      changes,         # new field values (for update)
        "reason":       reason,
        "requested_by": requested_by,
        "status":       "pending",       # pending | approved | rejected
        "handled_by":   None,
        "handle_note":  "",
        "created_at":   now,
        "handled_at":   None,
    }
    result = _col().insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)
    return doc


def list_requests(status: str | None = None, requested_by: str | None = None) -> list[dict]:
    query = {}
    if status:
        query["status"] = status
    if requested_by:
        query["requested_by"] = requested_by
    return [_clean(d) for d in _col().find(query).sort("created_at", DESCENDING)]


def get_request(req_id: str) -> dict | None:
    try:
        doc = _col().find_one({"_id": ObjectId(req_id)})
        return _clean(doc) if doc else None
    except Exception:
        return None


def handle_request(req_id: str, decision: str, handled_by: str, note: str = "") -> bool:
    """decision: 'approved' | 'rejected'"""
    result = _col().update_one(
        {"_id": ObjectId(req_id), "status": "pending"},
        {"$set": {
            "status":      decision,
            "handled_by":  handled_by,
            "handle_note": note,
            "handled_at":  _now(),
        }},
    )
    return result.matched_count > 0
