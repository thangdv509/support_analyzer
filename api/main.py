"""
QA Dashboard API — FastAPI backend for the support analyzer UI.

Run:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import os
import sys
import json
import time
import hashlib
import requests
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database.tunnel import ensure_tunnel
from database.connection import get_db
from database.deco_chat import ALL_GRADING_COLLECTIONS
from database.prompts import get_prompt_content
from analyzer_v2 import _parse_and_cap, GRADING_CRITERIA

# ---------------------------------------------------------------------------
# TTL Cache (in-memory, thread-safe enough for single-process uvicorn)
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, Any]] = {}
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # seconds, default 5 min


def _ck(*args: Any) -> str:
    """Build a cache key from arbitrary args."""
    raw = json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _cget(key: str) -> Any | None:
    if key in _CACHE:
        ts, val = _CACHE[key]
        if time.time() - ts < CACHE_TTL:
            return val
        del _CACHE[key]
    return None


def _cset(key: str, val: Any) -> None:
    _CACHE[key] = (time.time(), val)


def cache_clear() -> int:
    """Invalidate all cached responses. Returns number of entries cleared."""
    n = len(_CACHE)
    _CACHE.clear()
    return n


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

CRISP_IDENTIFIER = os.getenv("CRISP_IDENTIFIER")
CRISP_KEY = os.getenv("CRISP_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

ensure_tunnel()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="QA Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Auth router (OAuth + JWT + /me + /logout)
from api.auth import router as auth_router, get_current_user, require_admin, require_manager_or_admin
app.include_router(auth_router)

# Mount /assets early (sub-app, path-prefix matched before routes)
if os.path.isdir(_STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(_STATIC_DIR, "assets")), name="assets")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    """Check MongoDB connectivity and tunnel status."""
    import socket
    host = os.getenv("MONGO_HOST", "127.0.0.1")
    port = int(os.getenv("MONGO_PORT", "27018"))

    # TCP check
    try:
        with socket.create_connection((host, port), timeout=2):
            tcp_ok = True
    except OSError:
        tcp_ok = False

    # MongoDB ping
    mongo_ok = False
    mongo_error = None
    if tcp_ok:
        try:
            get_db().command("ping")
            mongo_ok = True
        except Exception as e:
            mongo_error = str(e)[:120]

    status = "ok" if mongo_ok else ("tunnel_broken" if tcp_ok else "tunnel_down")
    return {
        "status": status,
        "tunnel_port": f"{host}:{port}",
        "tcp_open": tcp_ok,
        "mongo_ok": mongo_ok,
        "mongo_error": mongo_error,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(doc: dict) -> dict:
    """Convert MongoDB doc to JSON-serializable dict."""
    result = {}
    for k, v in doc.items():
        if k == "_id":
            result["id"] = str(v)
        elif isinstance(v, ObjectId):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, dict):
            result[k] = _serialize(v)
        elif isinstance(v, list):
            result[k] = [_serialize(i) if isinstance(i, dict) else i for i in v]
        else:
            result[k] = v
    return result


def _app_to_col(app_name: str) -> str | None:
    if not app_name:
        return None
    u = app_name.upper()
    if "DECO" in u:
        return "grading_deco"
    if "SEARCHPIE" in u or "SEARCH PIE" in u:
        return "grading_searchpie"
    return None


def _find_doc(record_id: str) -> tuple[dict, str]:
    """Find doc by MongoDB _id string across all collections."""
    try:
        oid = ObjectId(record_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid record ID")
    db = get_db()
    for col_name in ALL_GRADING_COLLECTIONS:
        doc = db[col_name].find_one({"_id": oid})
        if doc:
            return doc, col_name
    raise HTTPException(status_code=404, detail="Record not found")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RecordUpdate(BaseModel):
    customer: Optional[str] = None
    primary_operator: Optional[str] = None
    is_resolved: Optional[bool] = None
    summary: Optional[str] = None
    tags: Optional[list[str]] = None
    grading: Optional[dict] = None


class RegradeRequest(BaseModel):
    feedback: Optional[str] = None  # appended to active prompt, not replace


# ---------------------------------------------------------------------------
# Routes — Records
# ---------------------------------------------------------------------------

@app.get("/api/records")
def list_records(
    app: str = Query("", description="DECO | SearchPie | empty = all"),
    agent: str = Query("", description="Agent name (partial match)"),
    date_from: str = Query("", description="YYYY-MM-DD"),
    date_to: str = Query("", description="YYYY-MM-DD"),
    score_min: float = Query(0.0, ge=0, le=10),
    score_max: float = Query(10.0, ge=0, le=10),
    is_resolved: Optional[bool] = Query(None),
    chat_link: str = Query("", description="session_id or Crisp URL (partial match)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=10000),
    sort_by: str = Query("date", description="date | final_score_10 | primary_operator | customer | app"),
    sort_dir: int = Query(-1, description="-1 desc | 1 asc"),
):
    # Check cache first
    ck = _ck("records", app, agent, date_from, date_to, score_min, score_max,
             is_resolved, chat_link, page, page_size, sort_by, sort_dir)
    cached = _cget(ck)
    if cached is not None:
        return cached

    db = get_db()

    if app:
        col_name = _app_to_col(app)
        col_names = [col_name] if col_name else []
    else:
        col_names = list(ALL_GRADING_COLLECTIONS)

    query: dict[str, Any] = {}
    if date_from and date_to:
        query["date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date"] = {"$gte": date_from}
    elif date_to:
        query["date"] = {"$lte": date_to}

    if agent:
        query["primary_operator"] = {"$regex": agent, "$options": "i"}

    if is_resolved is not None:
        query["is_resolved"] = is_resolved

    if score_min > 0 or score_max < 10:
        query["grading.final_score_10"] = {"$gte": score_min, "$lte": score_max}

    if chat_link:
        # Extract session_id from Crisp URL if user pastes full link
        # URL format: .../inbox/session_xxx/ or .../inbox/session_xxx
        import re
        m = re.search(r'session_[a-f0-9\-]+', chat_link)
        sid = m.group(0) if m else chat_link.strip()
        query["session_id"] = {"$regex": re.escape(sid), "$options": "i"}

    sort_field_map = {
        "date": "date",
        "final_score_10": "grading.final_score_10",
        "primary_operator": "primary_operator",
        "customer": "customer",
        "app": "app",
    }
    sort_field = sort_field_map.get(sort_by, "date")

    # Fetch from all relevant collections
    all_docs: list[dict] = []
    total = 0

    for col_name in col_names:
        col = db[col_name]
        total += col.count_documents(query)
        docs = list(col.find(query).sort(sort_field, sort_dir))
        all_docs.extend(docs)

    # Re-sort: primary by requested field, secondary by score (same direction) within same date
    def _sort_key(d: dict):
        date_val  = d.get("date", "")
        score_val = d.get("grading", {}).get("final_score_10", 0) or 0
        if sort_field == "date":
            return (date_val, score_val)  # reverse=True → newest date first, highest score first
        if sort_field == "grading.final_score_10":
            return (score_val, date_val)
        return (d.get(sort_field, "") or "", "")

    all_docs.sort(key=_sort_key, reverse=(sort_dir == -1))

    # Paginate
    skip = (page - 1) * page_size
    page_docs = all_docs[skip : skip + page_size]

    result = {
        "total": total,
        "page": page,
        "page_size": page_size,
        "records": [_serialize(d) for d in page_docs],
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _cset(ck, result)
    return result


@app.get("/api/records/{record_id}")
def get_record(record_id: str):
    doc, _ = _find_doc(record_id)
    return _serialize(doc)


@app.put("/api/records/{record_id}")
def update_record(record_id: str, body: RecordUpdate):
    doc, col_name = _find_doc(record_id)

    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if body.customer is not None:
        updates["customer"] = body.customer
    if body.primary_operator is not None:
        updates["primary_operator"] = body.primary_operator
    if body.is_resolved is not None:
        updates["is_resolved"] = body.is_resolved
    if body.summary is not None:
        updates["summary"] = body.summary
    if body.tags is not None:
        updates["tags"] = body.tags
    if body.grading is not None:
        updates["grading"] = body.grading

    get_db()[col_name].update_one({"_id": doc["_id"]}, {"$set": updates})
    cache_clear()
    updated = get_db()[col_name].find_one({"_id": doc["_id"]})
    return _serialize(updated)


@app.delete("/api/records/{record_id}")
def delete_record(record_id: str):
    doc, col_name = _find_doc(record_id)
    get_db()[col_name].delete_one({"_id": doc["_id"]})
    cache_clear()
    return {"ok": True, "deleted": record_id}


# ---------------------------------------------------------------------------
# Routes — Re-grade
# ---------------------------------------------------------------------------

@app.post("/api/records/{record_id}/regrade")
def regrade_record(record_id: str, body: RegradeRequest = RegradeRequest()):
    doc, col_name = _find_doc(record_id)

    transcript = doc.get("transcript", "")
    if not transcript:
        raise HTTPException(status_code=400, detail="No transcript available for re-grading")

    # Always use the active prompt — feedback is appended as extra context, never replaces
    base_prompt = get_prompt_content() or GRADING_CRITERIA
    if body.feedback and body.feedback.strip():
        prompt = (
            base_prompt
            + f"\n\nGÓP Ý BỔ SUNG CHO CHAT NÀY (ưu tiên xem xét khi chấm):\n{body.feedback.strip()}"
        )
    else:
        prompt = base_prompt

    _FORMAT_REMINDER = (
        "\n\nQUAN TRỌNG: Chỉ trả về JSON với đúng cấu trúc sau, không thêm gì khác:\n"
        '{"criteria": {"greetings": {"score": ..., "justification": "..."}, '
        '"grammar": {"score": ..., "justification": "..."}, '
        '"communication": {"score": ..., "justification": "..."}, '
        '"listening": {"score": ..., "justification": "..."}, '
        '"tone_pace": {"score": ..., "justification": "..."}, '
        '"empathy": {"score": ..., "justification": "..."}, '
        '"enthusiastic": {"score": ..., "justification": "..."}, '
        '"probing": {"score": ..., "justification": "..."}, '
        '"solution": {"score": ..., "justification": "..."}, '
        '"proactiveness": {"score": ..., "justification": "..."}, '
        '"transferring": {"score": ..., "justification": "..."}, '
        '"resources": {"score": ..., "justification": "..."}, '
        '"extra_mile": {"score": ..., "justification": "..."}, '
        '"review_asking": {"score": ..., "justification": "..."}}, '
        '"overall_summary": "..."}'
    )

    import time as _time
    last_err = ""
    grading = None
    for attempt in range(1, 4):  # retry up to 3 times
        # On retry, append explicit format reminder to user message
        user_content = f"Chấm đoạn chat sau:\n\n{transcript}"
        if attempt > 1:
            user_content += _FORMAT_REMINDER

        call_messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": call_messages,
                    "response_format": {"type": "json_object"},
                    "max_tokens": 4096,
                },
                timeout=120,
            )
            if r.status_code == 429:
                _time.sleep(10 * attempt)
                continue
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            grading = _parse_and_cap(raw)
            break
        except HTTPException:
            raise
        except Exception as e:
            last_err = str(e)
            print(f"[regrade] attempt {attempt}/3 failed: {last_err}")
            if attempt < 3:
                _time.sleep(3 * attempt)

    if grading is None:
        raise HTTPException(
            status_code=500,
            detail=f"Re-grading failed after 3 attempts: {last_err}",
        )

    now = datetime.now(timezone.utc)
    get_db()[col_name].update_one(
        {"_id": doc["_id"]},
        {"$set": {"grading": grading, "updated_at": now}},
    )
    cache_clear()
    updated = get_db()[col_name].find_one({"_id": doc["_id"]})
    return _serialize(updated)


# ---------------------------------------------------------------------------
# Routes — Crisp Resolve
# ---------------------------------------------------------------------------

@app.post("/api/records/{record_id}/resolve")
def resolve_record(record_id: str):
    doc, col_name = _find_doc(record_id)

    if doc.get("is_resolved"):
        return {"ok": True, "message": "Already resolved", "record": _serialize(doc)}

    website_id = doc.get("website_id")
    session_id = doc.get("session_id")

    if not website_id or not session_id:
        raise HTTPException(status_code=400, detail="Missing website_id or session_id in record")

    if not CRISP_IDENTIFIER or not CRISP_KEY:
        raise HTTPException(status_code=500, detail="Crisp credentials not configured in .env")

    url = f"https://api.crisp.chat/v1/website/{website_id}/conversation/{session_id}/state"
    try:
        r = requests.patch(
            url,
            auth=(CRISP_IDENTIFIER, CRISP_KEY),
            headers={"X-Crisp-Tier": "plugin", "Content-Type": "application/json"},
            json={"state": "resolved"},
            timeout=30,
        )
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Conversation not found in Crisp")
        if r.status_code == 429:
            raise HTTPException(status_code=429, detail="Crisp rate limit — try again in a moment")
        if r.status_code not in (200, 204):
            raise HTTPException(
                status_code=r.status_code,
                detail=f"Crisp API returned {r.status_code}: {r.text[:200]}",
            )
    except HTTPException:
        raise
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Crisp API unreachable: {str(e)}")

    # Mark resolved in DB
    now = datetime.now(timezone.utc)
    get_db()[col_name].update_one(
        {"_id": doc["_id"]},
        {"$set": {"is_resolved": True, "updated_at": now}},
    )
    cache_clear()
    updated = get_db()[col_name].find_one({"_id": doc["_id"]})
    return {"ok": True, "record": _serialize(updated)}


# ---------------------------------------------------------------------------
# Routes — Meta
# ---------------------------------------------------------------------------

@app.get("/api/agents")
def list_agents(app: str = Query("")):
    db = get_db()
    col_names = [_app_to_col(app)] if app else list(ALL_GRADING_COLLECTIONS)
    col_names = [n for n in col_names if n]

    agents: set[str] = set()
    for col_name in col_names:
        agents.update(db[col_name].distinct("primary_operator"))

    return sorted(a for a in agents if a)


@app.get("/api/stats")
def get_stats(
    app: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
):
    ck = _ck("stats", app, date_from, date_to)
    cached = _cget(ck)
    if cached is not None:
        return cached

    db = get_db()
    col_names = [_app_to_col(app)] if app else list(ALL_GRADING_COLLECTIONS)
    col_names = [n for n in col_names if n]

    query: dict[str, Any] = {}
    if date_from and date_to:
        query["date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date"] = {"$gte": date_from}
    elif date_to:
        query["date"] = {"$lte": date_to}

    projection = {"grading.final_score_10": 1, "primary_operator": 1, "app": 1, "is_resolved": 1}
    all_docs: list[dict] = []
    for col_name in col_names:
        all_docs.extend(db[col_name].find(query, projection))

    if not all_docs:
        return {"total": 0, "avg_score": None, "min_score": None, "max_score": None, "by_agent": {}, "by_app": {}}

    scores = [
        d["grading"]["final_score_10"]
        for d in all_docs
        if d.get("grading") and d["grading"].get("final_score_10") is not None
    ]

    by_agent: dict[str, dict] = {}
    for d in all_docs:
        agent = d.get("primary_operator") or "Unknown"
        score = d.get("grading", {}).get("final_score_10")
        if agent not in by_agent:
            by_agent[agent] = {"count": 0, "scores": []}
        by_agent[agent]["count"] += 1
        if score is not None:
            by_agent[agent]["scores"].append(score)

    agent_stats = {
        a: {
            "count": v["count"],
            "avg_score": round(sum(v["scores"]) / len(v["scores"]), 2) if v["scores"] else None,
        }
        for a, v in by_agent.items()
    }

    by_app: dict[str, int] = {}
    for d in all_docs:
        app_name = d.get("app") or "Unknown"
        by_app[app_name] = by_app.get(app_name, 0) + 1

    result = {
        "total": len(all_docs),
        "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "by_agent": agent_stats,
        "by_app": by_app,
    }
    _cset(ck, result)
    return result


@app.post("/api/cache/clear")
def clear_cache():
    n = cache_clear()
    return {"ok": True, "cleared": n}


# ---------------------------------------------------------------------------
# Routes — User management
# ---------------------------------------------------------------------------

class AddUserBody(BaseModel):
    email: str
    role: str  # admin | manager | support


class UpdateRoleBody(BaseModel):
    role: str


@app.get("/api/users")
def list_users_endpoint(user: dict = Depends(require_manager_or_admin)):
    from database.users import list_users
    return list_users()


@app.post("/api/users")
def add_user(body: AddUserBody, user: dict = Depends(require_manager_or_admin)):
    from database.users import create_user, VALID_ROLES
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {VALID_ROLES}")
    if user["role"] == "manager" and body.role != "support":
        raise HTTPException(status_code=403, detail="Managers can only add supporters")
    create_user(body.email.lower().strip(), body.role, user["sub"])
    return {"ok": True}


@app.put("/api/users/{email}/role")
def update_user_role(email: str, body: UpdateRoleBody, user: dict = Depends(require_admin)):
    from database.users import update_role, VALID_ROLES
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role")
    if not update_role(email, body.role):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@app.delete("/api/users/{email}")
def remove_user(email: str, user: dict = Depends(require_admin)):
    if email.lower() == user["sub"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    from database.users import delete_user
    if not delete_user(email):
        raise HTTPException(status_code=404, detail="User not found")
    return {"ok": True}


@app.get("/api/users/agent-map")
def get_agent_map_endpoint():
    """Public: returns {crisp_nickname: user_info} for agent column linking."""
    from database.users import get_agent_map
    return get_agent_map()


def _fetch_crisp_operators() -> list[dict]:
    """Fetch all unique operators across all Crisp websites."""
    if not CRISP_IDENTIFIER or not CRISP_KEY:
        raise HTTPException(status_code=503, detail="Crisp credentials not configured")
    headers = {"X-Crisp-Tier": "plugin"}
    auth = (CRISP_IDENTIFIER, CRISP_KEY)
    try:
        r = requests.get(
            "https://api.crisp.chat/v1/plugin/connect/websites/all/1",
            headers=headers, auth=auth,
            params={"filter_configured": "false"}, timeout=15,
        )
        websites = r.json().get("data", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Crisp API error: {e}")

    all_ops: list[dict] = []
    seen: set[str] = set()
    for site in (websites if isinstance(websites, list) else []):
        wid = site.get("website_id") if isinstance(site, dict) else None
        if not wid:
            continue
        try:
            r2 = requests.get(
                f"https://api.crisp.chat/v1/website/{wid}/operators/list",
                headers=headers, auth=auth, timeout=15,
            )
            ops = r2.json().get("data", [])
            for op in (ops if isinstance(ops, list) else []):
                details = op.get("details") or {}
                email = (details.get("email") or op.get("email") or "").lower().strip()
                if email and email not in seen:
                    seen.add(email)
                    all_ops.append(op)
        except Exception:
            continue
    return all_ops


@app.get("/api/crisp/agents", dependencies=[Depends(require_manager_or_admin)])
def list_crisp_operators():
    """List all operators from Crisp (for preview before sync)."""
    return _fetch_crisp_operators()


@app.post("/api/crisp/sync-agents", dependencies=[Depends(require_manager_or_admin)])
def sync_crisp_agents_endpoint():
    """Sync all Crisp operators to qa_users as support role."""
    operators = _fetch_crisp_operators()
    from database.users import sync_crisp_agents
    result = sync_crisp_agents(operators)
    cache_clear()
    return {**result, "total_fetched": len(operators)}


# ---------------------------------------------------------------------------
# Routes — Review Performance
# ---------------------------------------------------------------------------

class ReviewBody(BaseModel):
    status:        str = "Live"
    star:          str = "5"
    review_date:   str = ""
    customer_name: str = ""
    link:          str = ""
    app_plan:      str = "Free"
    mentioned:     str = ""
    cs1:           str = ""
    cs2:           str = ""
    tech:          str = ""
    count:         int = 1
    point:         float = 1.0
    he_so:         int = 1
    notes:         str = ""


class ReviewRequestBody(BaseModel):
    reason:  str = ""
    changes: dict = {}   # for update requests


class HandleRequestBody(BaseModel):
    note: str = ""


@app.get("/api/reviews")
def list_reviews(user: dict = Depends(get_current_user)):
    from database.reviews import list_reviews as _list
    return _list(viewer_email=user["sub"], viewer_role=user["role"])


@app.post("/api/reviews")
def create_review(body: ReviewBody, user: dict = Depends(get_current_user)):
    from database.reviews import create_review as _create
    return _create(body.model_dump(), created_by=user["sub"])


@app.put("/api/reviews/{review_id}")
def update_review(review_id: str, body: ReviewBody, user: dict = Depends(get_current_user)):
    from database.reviews import update_review as _update, get_review
    review = get_review(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if user["role"] in ("admin", "manager"):
        _update(review_id, body.model_dump())
        return get_review(review_id)
    raise HTTPException(403, "Use /api/reviews/{id}/request to propose changes")


@app.delete("/api/reviews/{review_id}")
def delete_review(review_id: str, user: dict = Depends(get_current_user)):
    from database.reviews import delete_review as _delete, get_review
    review = get_review(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    if user["role"] in ("admin", "manager"):
        _delete(review_id)
        return {"ok": True}
    raise HTTPException(403, "Use /api/reviews/{id}/request to propose deletion")


@app.post("/api/reviews/{review_id}/request")
def request_review_change(review_id: str, body: ReviewRequestBody,
                           action: str = Query("update", description="update | delete"),
                           user: dict = Depends(get_current_user)):
    from database.reviews import get_review
    from database.review_requests import create_request
    if not get_review(review_id):
        raise HTTPException(404, "Review not found")
    req = create_request(review_id, action, body.changes, body.reason, user["sub"])
    return req


@app.get("/api/review-requests")
def list_review_requests(status: str = Query("pending"),
                         user: dict = Depends(require_manager_or_admin)):
    from database.review_requests import list_requests
    return list_requests(status=status if status != "all" else None)


@app.post("/api/review-requests/{req_id}/approve")
def approve_review_request(req_id: str, body: HandleRequestBody = HandleRequestBody(),
                            user: dict = Depends(require_manager_or_admin)):
    from database.review_requests import get_request, handle_request
    from database.reviews import update_review as _update, delete_review as _delete

    req = get_request(req_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req["status"] != "pending":
        raise HTTPException(400, f"Request is already {req['status']}")

    if req["action"] == "delete":
        _delete(req["review_id"])
    elif req["action"] == "update":
        _update(req["review_id"], req["changes"])

    handle_request(req_id, "approved", user["sub"], body.note)
    return {"ok": True}


@app.post("/api/review-requests/{req_id}/reject")
def reject_review_request(req_id: str, body: HandleRequestBody = HandleRequestBody(),
                           user: dict = Depends(require_manager_or_admin)):
    from database.review_requests import get_request, handle_request
    req = get_request(req_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req["status"] != "pending":
        raise HTTPException(400, f"Request is already {req['status']}")
    handle_request(req_id, "rejected", user["sub"], body.note)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Routes — Review Stats
# ---------------------------------------------------------------------------

@app.get("/api/review-stats")
def review_stats(
    date_from: str = Query(""),
    date_to:   str = Query(""),
    user:      dict = Depends(get_current_user),
):
    """Aggregate review points per agent.
    - admin/manager: all agents
    - support: own stats only
    """
    from database.connection import get_db as _gdb

    db  = _gdb()
    col = db["qa_reviews"]

    query: dict[str, Any] = {}
    if date_from and date_to:
        query["review_date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["review_date"] = {"$gte": date_from}
    elif date_to:
        query["review_date"] = {"$lte": date_to}

    projection = {"mentioned": 1, "cs1": 1, "cs2": 1, "tech": 1,
                  "point": 1, "he_so": 1, "review_date": 1, "status": 1}
    reviews = list(col.find(query, projection))

    def _empty_stat(email: str) -> dict:
        return {"email": email, "total_count": 0, "total_point": 0.0,
                "by_role": {"mentioned": 0, "cs1": 0, "cs2": 0, "tech": 0}}

    stats: dict[str, dict] = {}
    for rev in reviews:
        # ── 1. Tính tổng điểm của review ────────────────────────────────────
        star            = (rev.get("star") or "").strip()
        plan            = (rev.get("app_plan") or "Free").strip()
        mentioned_email = (rev.get("mentioned") or "").strip()

        if star == "5":
            base  = 6.0 if plan == "Paid" else 1.0   # Free=1, Paid=6
            he_so = 2.0 if mentioned_email else 1.0   # có mention → x2
            total_point = base * he_so
        else:
            total_point = float(rev.get("point", 0) or 0)  # nhập thủ công

        # ── 2. Danh sách agent duy nhất tham gia review ─────────────────────
        unique_agents: list[str] = []
        seen: set[str] = set()
        for role in ("mentioned", "cs1", "cs2", "tech"):
            e = (rev.get(role) or "").strip().lower()
            if e and e not in seen:
                unique_agents.append(e)
                seen.add(e)

        n          = max(len(unique_agents), 1)
        each_point = round(total_point / n, 4)  # chia đều

        # ── 3. Cộng điểm cho từng agent (một lần mỗi review) ────────────────
        for email in unique_agents:
            if email not in stats:
                stats[email] = _empty_stat(email)
            stats[email]["total_count"] += 1
            stats[email]["total_point"]  = round(stats[email]["total_point"] + each_point, 2)

        # ── 4. Đếm số lần theo vai trò (không dedup) ────────────────────────
        for role in ("mentioned", "cs1", "cs2", "tech"):
            email = (rev.get(role) or "").strip().lower()
            if email:
                if email not in stats:
                    stats[email] = _empty_stat(email)
                stats[email]["by_role"][role] += 1

    if user["role"] == "support":
        own_email = user["sub"].lower()
        own = stats.get(own_email, {
            "email": own_email, "total_count": 0, "total_point": 0.0,
            "by_role": {"mentioned": 0, "cs1": 0, "cs2": 0, "tech": 0},
        })
        return [own]

    return sorted(stats.values(), key=lambda x: -x["total_point"])


# ---------------------------------------------------------------------------
# SPA fallback — MUST be registered LAST so API routes take priority
# ---------------------------------------------------------------------------

if os.path.isdir(_STATIC_DIR):
    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    def serve_spa(path: str = ""):
        index = os.path.join(_STATIC_DIR, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Frontend not built. Run: cd ui && npm run build")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
