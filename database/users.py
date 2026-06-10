"""
User management for the QA Dashboard.

Collection: qa_users
Schema:
    email       str  (unique, lowercase)
    name        str  (from Google profile)
    picture     str  (Google avatar URL)
    role        str  admin | manager | support
    added_by    str  (email of who created the account)
    created_at  datetime
    updated_at  datetime
    last_login  datetime | None
"""

from __future__ import annotations

from datetime import datetime, timezone
from pymongo import ASCENDING

from .connection import get_db

VALID_ROLES = ("admin", "manager", "support")
_COL = "qa_users"


def _col():
    col = get_db()[_COL]
    col.create_index([("email", ASCENDING)], unique=True, background=True)
    return col


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_user(email: str) -> dict | None:
    doc = _col().find_one({"email": email.lower()})
    return _clean(doc) if doc else None


def list_users() -> list[dict]:
    return [_clean(d) for d in _col().find({}).sort("created_at", ASCENDING)]


def user_exists(email: str) -> bool:
    return _col().count_documents({"email": email.lower()}, limit=1) > 0


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def upsert_on_login(email: str, name: str, picture: str, default_role: str = "support") -> dict:
    """Called every time a user logs in via Google OAuth.
    Creates the user if new (with default_role), updates profile fields.
    """
    now = _now()
    _col().update_one(
        {"email": email.lower()},
        {
            "$set": {
                "name": name,
                "picture": picture,
                "last_login": now,
                "updated_at": now,
            },
            "$setOnInsert": {
                "email": email.lower(),
                "role": default_role,
                "added_by": "system",
                "created_at": now,
            },
        },
        upsert=True,
    )
    return get_user(email)


def create_user(email: str, role: str, added_by: str) -> dict:
    """Pre-create a user slot (before they've logged in)."""
    now = _now()
    _col().update_one(
        {"email": email.lower()},
        {
            "$set": {"role": role, "added_by": added_by, "updated_at": now},
            "$setOnInsert": {
                "email": email.lower(),
                "name": email,
                "picture": "",
                "created_at": now,
            },
        },
        upsert=True,
    )
    return get_user(email)


def update_role(email: str, role: str) -> bool:
    result = _col().update_one(
        {"email": email.lower()},
        {"$set": {"role": role, "updated_at": _now()}},
    )
    return result.matched_count > 0


def update_nickname(email: str, nickname: str) -> bool:
    result = _col().update_one(
        {"email": email.lower()},
        {"$set": {"nickname": nickname.strip(), "updated_at": _now()}},
    )
    return result.matched_count > 0


def delete_user(email: str) -> bool:
    result = _col().delete_one({"email": email.lower()})
    return result.deleted_count > 0


def sync_crisp_agents(operators: list[dict]) -> dict:
    """Bulk-add Crisp operators as support users. Skip if email already exists (any role).
    Always updates crisp_nickname so the agent column can link records to users.
    """
    added = 0
    updated = 0
    now = _now()
    for op in operators:
        details = op.get("details") or {}
        email = (details.get("email") or op.get("email") or "").lower().strip()
        if not email:
            continue
        crisp_nickname = (
            details.get("nickname")
            or details.get("first_name")
            or email.split("@")[0]
        ).strip()
        avatar = details.get("avatar") or ""

        existing = _col().find_one({"email": email})
        if existing:
            _col().update_one(
                {"email": email},
                {"$set": {"crisp_nickname": crisp_nickname, "updated_at": now}},
            )
            updated += 1
        else:
            _col().insert_one({
                "email": email,
                "name": crisp_nickname,
                "nickname": "",
                "picture": avatar,
                "role": "support",
                "crisp_nickname": crisp_nickname,
                "added_by": "crisp_sync",
                "created_at": now,
                "updated_at": now,
                "last_login": None,
            })
            added += 1

    return {"added": added, "updated": updated}


def get_agent_map() -> dict:
    """Returns {crisp_nickname: user_info} for linking records to users."""
    result = {}
    for u in list_users():
        cn = (u.get("crisp_nickname") or "").strip()
        if cn:
            result[cn] = u
    return result
