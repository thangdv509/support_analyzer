"""
Auth helpers: allowed emails + access tokens.

Collections:
    auth_emails  — email allow-list  {email, active, added_at, updated_at}
    auth_tokens  — issued tokens     {token, email, created_at, expires_at, active}
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from .connection import get_db


# ---------------------------------------------------------------------------
# Email allow-list
# ---------------------------------------------------------------------------

def is_email_allowed(email: str) -> bool:
    return get_db()["auth_emails"].count_documents(
        {"email": email.lower(), "active": True}, limit=1
    ) > 0


def add_email(email: str) -> None:
    now = datetime.now(timezone.utc)
    get_db()["auth_emails"].update_one(
        {"email": email.lower()},
        {
            "$set":         {"email": email.lower(), "active": True, "updated_at": now},
            "$setOnInsert": {"added_at": now},
        },
        upsert=True,
    )


def remove_email(email: str) -> bool:
    result = get_db()["auth_emails"].update_one(
        {"email": email.lower()}, {"$set": {"active": False}}
    )
    return result.modified_count > 0


def list_emails() -> list[str]:
    return [
        doc["email"]
        for doc in get_db()["auth_emails"].find({"active": True}, {"email": 1})
    ]


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def store_token(email: str, expires_days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    get_db()["auth_tokens"].insert_one({
        "token":      token,
        "email":      email.lower(),
        "created_at": now,
        "expires_at": now + timedelta(days=expires_days),
        "active":     True,
    })
    return token


def validate_token(token: str) -> str | None:
    """Returns email if token is valid and active, None otherwise."""
    if not token:
        return None
    doc = get_db()["auth_tokens"].find_one({
        "token":      token,
        "active":     True,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    return doc["email"] if doc else None


def revoke_token(token: str) -> bool:
    result = get_db()["auth_tokens"].update_one(
        {"token": token}, {"$set": {"active": False}}
    )
    return result.modified_count > 0
