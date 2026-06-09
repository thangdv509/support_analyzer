"""
Review Performance tracking.

Collection: qa_reviews
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from bson import ObjectId
from pymongo import DESCENDING

from .connection import get_db

_COL = "qa_reviews"

STAR_OPTIONS = ["5", "GSC package", "SEO Map Package", "GMC Package",
                "VIP Scan", "Upgrade", "Plus", "Vip AI", "Speed Plan"]
STATUS_OPTIONS = ["Live", "Pending"]
PLAN_OPTIONS   = ["Free", "Paid"]


def _col():
    col = get_db()[_COL]
    col.create_index([("review_date", DESCENDING)], background=True)
    col.create_index([("created_by", 1)], background=True)
    col.create_index([("mentioned", 1)], background=True)
    col.create_index([("cs1", 1)], background=True)
    col.create_index([("cs2", 1)], background=True)
    return col


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    for k, v in doc.items():
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def list_reviews(viewer_email: str | None = None, viewer_role: str = "support") -> list[dict]:
    """
    admin/manager → all reviews.
    support → only rows where their email is in the mentioned field,
              OR they created the review.
    """
    query: dict[str, Any] = {}
    if viewer_role == "support" and viewer_email:
        query = {"$or": [
            {"mentioned":   viewer_email},
            {"cs1":         viewer_email},
            {"cs2":         viewer_email},
            {"tech":        viewer_email},
            {"created_by":  viewer_email},
        ]}
    return [_clean(d) for d in _col().find(query).sort("review_date", DESCENDING)]


def get_review(review_id: str) -> dict | None:
    try:
        doc = _col().find_one({"_id": ObjectId(review_id)})
        return _clean(doc) if doc else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def create_review(data: dict, created_by: str) -> dict:
    now = _now()
    doc = {
        "status":        data.get("status", "Live"),
        "star":          data.get("star", "5"),
        "review_date":   data.get("review_date", ""),
        "customer_name": data.get("customer_name", ""),
        "link":          data.get("link", ""),
        "app_plan":      data.get("app_plan", "Free"),
        "mentioned":     data.get("mentioned", ""),
        "cs1":           data.get("cs1", ""),
        "cs2":           data.get("cs2", ""),
        "tech":          data.get("tech", ""),
        "count":         int(data.get("count", 1)),
        "point":         float(data.get("point", 1.0)),
        "he_so":         int(data.get("he_so", 1)),
        "notes":         data.get("notes", ""),
        "created_by":    created_by,
        "created_at":    now,
        "updated_at":    now,
    }
    result = _col().insert_one(doc)
    return get_review(str(result.inserted_id))  # type: ignore[return-value]


def update_review(review_id: str, data: dict) -> bool:
    allowed = ["status", "star", "review_date", "customer_name", "link",
               "app_plan", "mentioned", "cs1", "cs2", "tech",
               "count", "point", "he_so", "notes"]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return False
    updates["updated_at"] = _now()
    result = _col().update_one({"_id": ObjectId(review_id)}, {"$set": updates})
    return result.matched_count > 0


def delete_review(review_id: str) -> bool:
    result = _col().delete_one({"_id": ObjectId(review_id)})
    return result.deleted_count > 0
