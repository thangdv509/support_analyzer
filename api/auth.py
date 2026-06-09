"""
Google OAuth2 + JWT auth for the QA Dashboard UI.

Flow:
    1. GET /api/auth/login  → redirect to Google consent screen
    2. GET /api/auth/callback?code=...  → exchange code, set JWT cookie, redirect to frontend
    3. GET /api/auth/me  → return current user payload from cookie
    4. POST /api/auth/logout  → clear cookie

Role hierarchy:
    admin   → full access: view/add/edit roles of anyone
    manager → can add supporters, view user list
    support → no user management access
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
JWT_SECRET           = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM        = "HS256"
JWT_EXPIRE_HOURS     = int(os.getenv("JWT_EXPIRE_HOURS", "168"))  # 7 days
BACKEND_URL          = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:5173")
ADMIN_EMAILS         = [
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "").split(",")
    if e.strip()
]

COOKIE_NAME    = "qa_session"
COOKIE_MAX_AGE = JWT_EXPIRE_HOURS * 3600

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_INFO_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _make_token(user: dict) -> str:
    payload = {
        "sub":     user["email"],
        "name":    user.get("name", ""),
        "picture": user.get("picture", ""),
        "role":    user.get("role", "support"),
        "exp":     datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please log in again")


# ---------------------------------------------------------------------------
# Dependency injectors
# ---------------------------------------------------------------------------

def get_current_user(qa_session: Optional[str] = Cookie(None)) -> dict:
    if not qa_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _decode_token(qa_session)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_manager_or_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Manager or admin access required")
    return user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/login")
def login():
    """Redirect browser to Google consent screen."""
    params = urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  f"{BACKEND_URL}/api/auth/callback",
        "response_type": "code",
        "scope":         "openid email profile",
        "access_type":   "offline",
        "prompt":        "select_account",
    })
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")


@router.get("/callback")
def callback(code: str):
    """Exchange OAuth code → user info → JWT cookie → redirect to frontend."""
    from database.users import get_user, upsert_on_login

    # 1. Exchange code for access token
    try:
        token_resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  f"{BACKEND_URL}/api/auth/callback",
                "grant_type":    "authorization_code",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
    except Exception as e:
        return RedirectResponse(f"{FRONTEND_URL}?error=oauth_failed")

    # 2. Fetch Google profile
    try:
        info_resp = httpx.get(
            GOOGLE_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        info_resp.raise_for_status()
        info = info_resp.json()
    except Exception:
        return RedirectResponse(f"{FRONTEND_URL}?error=oauth_failed")

    email   = info["email"].lower()
    name    = info.get("name", email)
    picture = info.get("picture", "")

    # 3. Check if user is allowed
    existing = get_user(email)
    if not existing:
        if email in ADMIN_EMAILS:
            default_role = "admin"
        else:
            # Not pre-registered → deny
            return RedirectResponse(f"{FRONTEND_URL}?error=not_authorized&email={email}")

    default_role = existing["role"] if existing else default_role  # type: ignore[possibly-undefined]
    user = upsert_on_login(email, name, picture, default_role)

    # 4. Issue JWT cookie
    token    = _make_token(user)
    redirect = RedirectResponse(FRONTEND_URL, status_code=302)
    redirect.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        secure=BACKEND_URL.startswith("https"),
    )
    return redirect


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    from database.users import get_user
    db_user = get_user(user["sub"])
    if not db_user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return {
        "email":    db_user["email"],
        "name":     db_user["name"],
        "nickname": db_user.get("nickname", ""),
        "picture":  db_user["picture"],
        "role":     db_user["role"],
    }


class UpdateProfileBody(BaseModel):
    nickname: str = ""


@router.put("/me")
def update_me(body: "UpdateProfileBody", user: dict = Depends(get_current_user)):
    from database.users import update_nickname
    update_nickname(user["sub"], body.nickname)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, samesite="lax")
    return {"ok": True}
