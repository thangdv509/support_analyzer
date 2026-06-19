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

STAR_RATINGS    = ["1", "2", "3", "4", "5"]
PACKAGE_OPTIONS = ["GSC package", "SEO Map Package", "GMC Package",
                   "VIP Scan", "Upgrade", "Plus", "Vip AI", "Speed Plan"]
APP_OPTIONS     = ["SearchPie", "DECO"]
STATUS_OPTIONS  = ["Live", "Pending"]
PLAN_OPTIONS    = ["Free", "Paid"]


def _col():
    col = get_db()[_COL]
    col.create_index([("review_date", DESCENDING)], background=True)
    col.create_index([("created_by", 1)], background=True)
    col.create_index([("mentioned", 1)], background=True)
    col.create_index([("cs1", 1)], background=True)
    col.create_index([("cs2", 1)], background=True)
    return col


def _next_seq() -> int:
    result = get_db()["counters"].find_one_and_update(
        {"_id": "qa_reviews"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return result["seq"]


def _migrate_seqs() -> None:
    """Assign seq to existing reviews that predate the field."""
    col = _col()
    missing = list(col.find({"seq": {"$exists": False}}).sort("_id", 1))
    if not missing:
        return
    max_doc = col.find_one({"seq": {"$exists": True}}, sort=[("seq", -1)])
    cur = max_doc["seq"] if max_doc else 0
    for rev in missing:
        cur += 1
        col.update_one({"_id": rev["_id"]}, {"$set": {"seq": cur}})
    get_db()["counters"].update_one(
        {"_id": "qa_reviews"}, {"$set": {"seq": cur}}, upsert=True
    )


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
    _migrate_seqs()
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

def _auto_score(star: str, app_plan: str, mentioned: str) -> tuple[float, int]:
    """Return (point, he_so) for 5-star reviews. Others get (0, 1)."""
    if star == "5":
        base  = 6.0 if app_plan == "Paid" else 1.0
        he_so = 2 if mentioned else 1
        return base * he_so, he_so
    return 0.0, 1


def create_review(data: dict, created_by: str) -> dict:
    now  = _now()
    star = data.get("star", "5")
    plan = data.get("app_plan", "Free")
    mentioned = data.get("mentioned", "")
    point, he_so = _auto_score(star, plan, mentioned)
    doc = {
        "seq":           _next_seq(),
        "status":        "Pending",
        "star":          star,
        "package":       data.get("package", ""),
        "app":           data.get("app", ""),
        "review_date":   data.get("review_date", ""),
        "customer_name": data.get("customer_name", ""),
        "link":          data.get("link", ""),
        "app_plan":      plan,
        "mentioned":     mentioned,
        "cs1":           data.get("cs1", ""),
        "cs2":           data.get("cs2", ""),
        "tech":          data.get("tech", ""),
        "count":         1,
        "point":         point,
        "he_so":         he_so,
        "notes":         data.get("notes", ""),
        "created_by":    created_by,
        "created_at":    now,
        "updated_at":    now,
    }
    result = _col().insert_one(doc)
    return get_review(str(result.inserted_id))  # type: ignore[return-value]


def update_review(review_id: str, data: dict) -> bool:
    """General update — count/point/he_so are excluded (use update_score for those)."""
    allowed = ["status", "star", "package", "app", "review_date", "customer_name", "link",
               "app_plan", "mentioned", "cs1", "cs2", "tech", "notes"]
    updates = {k: data[k] for k in allowed if k in data}
    # Re-calculate point/he_so if star/plan/mentioned changed and star == "5"
    star      = updates.get("star")      or data.get("star", "")
    app_plan  = updates.get("app_plan")  or data.get("app_plan", "Free")
    mentioned = updates.get("mentioned") or data.get("mentioned", "")
    if star == "5":
        point, he_so = _auto_score(star, app_plan, mentioned)
        updates["point"]  = point
        updates["he_so"]  = he_so
    elif star in ("1", "2", "3", "4"):
        updates["point"]  = 0.0
        updates["he_so"]  = 1
    if not updates:
        return False
    updates["updated_at"] = _now()
    result = _col().update_one({"_id": ObjectId(review_id)}, {"$set": updates})
    return result.matched_count > 0


def update_score(review_id: str, count: int, point: float, he_so: int) -> bool:
    """Admin/manager only — update count, point, he_so."""
    result = _col().update_one(
        {"_id": ObjectId(review_id)},
        {"$set": {"count": count, "point": point, "he_so": he_so, "updated_at": _now()}},
    )
    return result.matched_count > 0


def delete_review(review_id: str) -> bool:
    result = _col().delete_one({"_id": ObjectId(review_id)})
    return result.deleted_count > 0
