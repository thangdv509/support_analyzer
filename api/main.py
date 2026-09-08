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
from database.crawl_stats import get_stats as get_crawl_stats
from grading.analyzer_v2 import _parse_and_cap, GRADING_CRITERIA

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
_ASSETS_DIR = os.path.join(_STATIC_DIR, "assets")
os.makedirs(_ASSETS_DIR, exist_ok=True)
app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")


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


def _extract_customer_issue(transcript: str) -> str:
    """Lấy 1-2 tin nhắn đầu của KHÁCH trong transcript — để biết chat này về vấn đề gì.
    (overall_summary chỉ đánh giá hiệu suất agent, không mô tả nội dung vấn đề khách hỏi).
    Format transcript (xem analyzer_v2.py): operator lines thụt "  " (2 space), customer thì không."""
    blocks = transcript.split("\n\n")
    found = []
    for block in blocks:
        if not block.strip():
            continue
        if block.startswith("---") or block.startswith("[Agent"):
            continue
        if block.startswith("  "):  # operator
            continue
        first_line = block.strip().split("\n")[0]
        content = first_line.split(":", 1)[1].strip() if ":" in first_line else first_line.strip()
        if content:
            found.append(content)
        if len(found) >= 2:
            break
    return " / ".join(found)[:250]


@app.get("/api/agent-summary", dependencies=[Depends(require_manager_or_admin)])
def agent_summary(
    agent:     str = Query(...),
    app:       str = Query(""),
    date_from: str = Query(""),
    date_to:   str = Query(""),
):
    """Tổng hợp đánh giá tổng quan 1 agent (Ưu điểm/Nhược điểm/Cần cải thiện) bằng LLM,
    dựa trên toàn bộ chat đã chấm của agent đó trong khoảng ngày được chọn."""
    from database.deco_chat import get_chats_by_date_range

    ck = _ck("agent-summary", agent, app, date_from, date_to)
    cached = _cget(ck)
    if cached is not None:
        return cached

    chats = get_chats_by_date_range(
        date_from or "0000-01-01", date_to or "9999-12-31",
        operator=agent, app=app or None,
    )
    if not chats:
        raise HTTPException(status_code=404, detail="Không có chat nào của agent này trong khoảng thời gian đã chọn")

    MAX_CHATS = 150  # tránh prompt quá dài nếu khoảng ngày rất rộng
    truncated = len(chats) > MAX_CHATS
    sample = chats[-MAX_CHATS:] if truncated else chats

    digest_lines = []
    for c in sample:
        g = c.get("grading") or {}
        score = g.get("final_score_10")
        summary = (g.get("overall_summary") or "").strip()
        issue = _extract_customer_issue(c.get("transcript", ""))
        digest_lines.append(f"- [{c.get('date')}] ({c.get('app')}) Điểm: {score}/10")
        if issue:
            digest_lines.append(f"    Khách hỏi: {issue}")
        digest_lines.append(f"    Đánh giá: {summary}")

        criteria = g.get("criteria") or {}
        weak = sorted(
            ((k, v) for k, v in criteria.items() if isinstance(v, dict)),
            key=lambda kv: kv[1].get("score", 999),
        )[:2]
        for key, val in weak:
            justification = (val.get("justification") or "").strip()[:200]
            if justification:
                digest_lines.append(f"    · {key} ({val.get('score')}đ): {justification}")

    digest = "\n".join(digest_lines)
    note = f"\n(Lưu ý: agent có {len(chats)} chat trong khoảng này, chỉ lấy mẫu {MAX_CHATS} chat gần nhất để tổng hợp.)" if truncated else ""

    system_prompt = (
        "Bạn là quản lý QA đang tổng hợp đánh giá tổng quan hiệu suất của 1 agent support, "
        "dựa trên dữ liệu chấm điểm chi tiết từng chat được cung cấp. Chỉ trả lời bằng JSON "
        "đúng format được yêu cầu, không thêm chữ nào khác ngoài JSON."
    )
    user_prompt = f"""Tổng hợp đánh giá TỔNG QUAN cho agent support "{agent}", dựa trên {len(sample)}
cuộc chat đã được chấm điểm trong khoảng thời gian được chọn.{note}

DỮ LIỆU CHẤM ĐIỂM TỪNG CHAT (điểm số + khách hỏi gì + tóm tắt đánh giá + tiêu chí bị trừ điểm nếu có):
{digest}

Hãy tổng hợp đánh giá TỔNG QUAN về agent này (nhìn xu hướng lặp lại qua nhiều chat, KHÔNG liệt kê
lại từng chat riêng lẻ), gồm đúng 4 phần:
- "strengths": các ưu điểm nổi bật, nhất quán qua nhiều chat
- "weaknesses": các nhược điểm/vấn đề lặp lại nhiều lần
- "improvements": gợi ý cụ thể, hành động được, để agent cải thiện
- "common_issues": tổng quan các LOẠI vấn đề/câu hỏi mà khách hàng hay hỏi agent này nhất
  (gộp nhóm theo chủ đề, vd "hỏi cách setup schema markup", "khiếu nại billing/refund",
  "báo lỗi hiển thị badge trên theme", ... — KHÔNG phải đánh giá hiệu suất, chỉ là nội dung vấn đề)

Mỗi phần là 1 danh sách các câu ngắn gọn, cụ thể (không chung chung), viết bằng tiếng Việt.
Nếu không đủ dữ liệu cho 1 phần nào đó, để danh sách rỗng, không bịa.
Trả về BẮT BUỘC đúng JSON sau, không thêm chữ nào khác:
{{"strengths": ["..."], "weaknesses": ["..."], "improvements": ["..."], "common_issues": ["..."]}}
"""

    import time as _time
    last_err = ""
    parsed = None
    for attempt in range(1, 4):
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 2048,
                },
                timeout=120,
            )
            if r.status_code == 429:
                _time.sleep(10 * attempt)
                continue
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw)
            break
        except Exception as e:
            last_err = str(e)
            print(f"[agent-summary] attempt {attempt}/3 failed: {last_err}")
            if attempt < 3:
                _time.sleep(3 * attempt)

    if parsed is None:
        raise HTTPException(status_code=500, detail=f"Summarize failed after 3 attempts: {last_err}")

    result = {
        "agent": agent,
        "chat_count": len(chats),
        "sampled_count": len(sample),
        "strengths": parsed.get("strengths", []),
        "weaknesses": parsed.get("weaknesses", []),
        "improvements": parsed.get("improvements", []),
        "common_issues": parsed.get("common_issues", []),
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
def list_users_endpoint(user: dict = Depends(get_current_user)):
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
    star:          str = "5"
    package:       str = ""
    app:           str = ""
    review_date:   str = ""
    customer_name: str = ""
    link:          str = ""
    app_plan:      str = "Free"
    mentioned:     str = ""
    cs1:           str = ""
    cs2:           str = ""
    tech:          str = ""
    notes:         str = ""


class ReviewUpdateBody(BaseModel):
    status:        str = "Pending"
    star:          str = "5"
    package:       str = ""
    app:           str = ""
    review_date:   str = ""
    customer_name: str = ""
    link:          str = ""
    app_plan:      str = "Free"
    mentioned:     str = ""
    cs1:           str = ""
    cs2:           str = ""
    tech:          str = ""
    notes:         str = ""


class ReviewScoreBody(BaseModel):
    count: int   = 1
    point: float = 0.0
    he_so: int   = 1


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
def update_review(review_id: str, body: ReviewUpdateBody, user: dict = Depends(get_current_user)):
    from database.reviews import update_review as _update, get_review
    review = get_review(review_id)
    if not review:
        raise HTTPException(404, "Review not found")
    data = body.model_dump()
    if user["role"] not in ("admin", "manager"):
        data.pop("status", None)  # support cannot change status
        raise HTTPException(403, "Use /api/reviews/{id}/request to propose changes")
    _update(review_id, data)
    cache_clear()
    return get_review(review_id)


@app.patch("/api/reviews/{review_id}/score")
def update_review_score(review_id: str, body: ReviewScoreBody,
                        user: dict = Depends(require_manager_or_admin)):
    from database.reviews import update_score, get_review
    if not get_review(review_id):
        raise HTTPException(404, "Review not found")
    update_score(review_id, body.count, body.point, body.he_so)
    cache_clear()
    return get_review(review_id)


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
    app_name:  str = Query("", alias="app"),
    user:      dict = Depends(get_current_user),
):
    """Aggregate review points per agent (Live reviews only).
    - admin/manager: all agents
    - support: own stats only
    """
    from database.connection import get_db as _gdb

    db  = _gdb()
    col = db["qa_reviews"]

    query: dict[str, Any] = {"status": "Live", "package": {"$ne": "Upgrade"}}
    if app_name:
        query["app"] = app_name
    if date_from and date_to:
        query["review_date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["review_date"] = {"$gte": date_from}
    elif date_to:
        query["review_date"] = {"$lte": date_to}

    projection = {"mentioned": 1, "cs1": 1, "cs2": 1, "tech": 1,
                  "point": 1, "he_so": 1, "review_date": 1, "status": 1, "package": 1}
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
            stats[email]["total_point"] = round(stats[email]["total_point"] + each_point, 2)

        # "Tổng reviews" chỉ tính cho CS1 — mentioned/cs2/tech chỉ liên quan thưởng,
        # không tính là review.
        cs1_email = (rev.get("cs1") or "").strip().lower()
        if cs1_email:
            if cs1_email not in stats:
                stats[cs1_email] = _empty_stat(cs1_email)
            stats[cs1_email]["total_count"] += 1

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
# Routes — QA Score Trend (per-agent, grouped by time)
# ---------------------------------------------------------------------------

@app.get("/api/qa-score-trend")
def qa_score_trend(
    agent:     str = Query(""),
    group_by:  str = Query("month"),   # day | month | year
    date_from: str = Query(""),
    date_to:   str = Query(""),
    app_filter: str = Query("", alias="app"),
    user:      dict = Depends(get_current_user),
):
    from collections import defaultdict
    slice_len = {"day": 10, "month": 7, "year": 4}.get(group_by, 7)

    col_names = [_app_to_col(app_filter)] if app_filter else list(ALL_GRADING_COLLECTIONS)
    col_names = [n for n in col_names if n]

    query: dict[str, Any] = {}
    if agent:
        query["primary_operator"] = agent
    if date_from and date_to:
        query["date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date"] = {"$gte": date_from}
    elif date_to:
        query["date"] = {"$lte": date_to}

    db = get_db()
    buckets: dict[str, list[float]] = defaultdict(list)
    for col_name in col_names:
        for doc in db[col_name].find(query, {"date": 1, "grading.final_score_10": 1}):
            bucket = (doc.get("date") or "")[:slice_len]
            if not bucket:
                continue
            score = doc.get("grading", {}).get("final_score_10")
            if score is not None:
                buckets[bucket].append(float(score))

    result = sorted([
        {
            "date":      b,
            "avg_score": round(sum(scores) / len(scores), 2),
            "count":     len(scores),
        }
        for b, scores in buckets.items()
    ], key=lambda x: x["date"])
    return result


# ---------------------------------------------------------------------------
# Routes — Review Trend (per-agent, grouped by time + app)
# ---------------------------------------------------------------------------

@app.get("/api/review-trend")
def review_trend(
    agent:     str = Query(""),
    group_by:  str = Query("month"),   # day | month | year
    date_from: str = Query(""),
    date_to:   str = Query(""),
    app_name:  str = Query("", alias="app"),
    user:      dict = Depends(get_current_user),
):
    from database.connection import get_db as _gdb
    from database.reviews import APP_OPTIONS

    db  = _gdb()
    col = db["qa_reviews"]

    # Slice length for grouping
    slice_len = {"day": 10, "month": 7, "year": 4}.get(group_by, 7)

    match: dict[str, Any] = {"status": "Live"}
    if app_name:
        match["app"] = app_name
    if date_from and date_to:
        match["review_date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        match["review_date"] = {"$gte": date_from}
    elif date_to:
        match["review_date"] = {"$lte": date_to}
    if agent:
        match["$or"] = [
            {"mentioned": agent}, {"cs1": agent}, {"cs2": agent}, {"tech": agent}
        ]

    pipeline = [
        {"$match": match},
        {"$addFields": {
            "bucket": {"$substrCP": ["$review_date", 0, slice_len]},
            "app_key": {"$ifNull": ["$app", ""]},
        }},
        {"$group": {
            "_id": {"date": "$bucket", "app": "$app_key"},
            "count": {"$sum": 1},
            "point": {"$sum": "$point"},
        }},
        {"$sort": {"_id.date": 1}},
    ]

    raw = list(col.aggregate(pipeline))

    # Collect all dates and apps, then pivot
    all_dates: list[str] = sorted({r["_id"]["date"] for r in raw if r["_id"]["date"]})
    all_apps  = APP_OPTIONS  # fixed order

    # Build {date: {app: count}}
    pivot: dict[str, dict[str, int]] = {d: {a: 0 for a in all_apps} for d in all_dates}
    for r in raw:
        d = r["_id"]["date"]
        a = r["_id"]["app"]
        if d in pivot and a in all_apps:
            pivot[d][a] = r["count"]

    result = [{"date": d, **pivot[d]} for d in all_dates]
    return {"data": result, "apps": all_apps}


# ---------------------------------------------------------------------------
# Routes — Analytics overview (Crisp-style)
# ---------------------------------------------------------------------------

@app.get("/api/analytics", dependencies=[Depends(require_manager_or_admin)])
def get_analytics(
    app_filter: str = Query("", alias="app"),
    date_from:  str = Query(""),
    date_to:    str = Query(""),
    group_by:   str = Query("day"),   # day | month | year
):
    from collections import defaultdict

    slice_len = {"day": 10, "month": 7, "year": 4}.get(group_by, 10)

    col_names = [_app_to_col(app_filter)] if app_filter else list(ALL_GRADING_COLLECTIONS)
    col_names = [n for n in col_names if n]

    query: dict[str, Any] = {}
    if date_from and date_to:
        query["date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date"] = {"$gte": date_from}
    elif date_to:
        query["date"] = {"$lte": date_to}

    db = get_db()
    projection = {"date": 1, "grading.final_score_10": 1, "primary_operator": 1, "app": 1}
    all_docs: list[dict] = []
    for col_name in col_names:
        all_docs.extend(db[col_name].find(query, projection))

    APP_KEYS = ["DECO", "SearchPie"]
    DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    # ── Time series ──────────────────────────────────────────────────────────
    ts_map: dict[str, dict] = {}
    for doc in all_docs:
        bucket = (doc.get("date") or "")[:slice_len]
        if not bucket:
            continue
        if bucket not in ts_map:
            ts_map[bucket] = {"total": 0, "scores": [], **{ak: 0 for ak in APP_KEYS}, **{f"_s_{ak}": [] for ak in APP_KEYS}}
        score = doc.get("grading", {}).get("final_score_10")
        ak = doc.get("app") or ""
        ts_map[bucket]["total"] += 1
        if ak in APP_KEYS:
            ts_map[bucket][ak] += 1
            if score is not None:
                ts_map[bucket][f"_s_{ak}"].append(score)
        if score is not None:
            ts_map[bucket]["scores"].append(score)

    time_series = []
    for bucket in sorted(ts_map.keys()):
        d = ts_map[bucket]
        entry: dict[str, Any] = {
            "date": bucket,
            "total": d["total"],
            "avg_score": round(sum(d["scores"]) / len(d["scores"]), 2) if d["scores"] else None,
        }
        for ak in APP_KEYS:
            entry[ak] = d[ak]
            s = d[f"_s_{ak}"]
            entry[f"avg_{ak}"] = round(sum(s) / len(s), 2) if s else None
        time_series.append(entry)

    # ── By agent ─────────────────────────────────────────────────────────────
    agent_map: dict[str, dict] = {}
    for doc in all_docs:
        ag = doc.get("primary_operator") or "Unknown"
        score = doc.get("grading", {}).get("final_score_10")
        ak = doc.get("app") or ""
        if ag not in agent_map:
            agent_map[ag] = {"count": 0, "scores": [], **{ak2: 0 for ak2 in APP_KEYS}}
        agent_map[ag]["count"] += 1
        if ak in APP_KEYS:
            agent_map[ag][ak] += 1
        if score is not None:
            agent_map[ag]["scores"].append(score)

    by_agent = sorted([
        {
            "agent": a,
            "count": v["count"],
            "avg_score": round(sum(v["scores"]) / len(v["scores"]), 2) if v["scores"] else None,
            **{ak: v[ak] for ak in APP_KEYS},
        }
        for a, v in agent_map.items()
    ], key=lambda x: -x["count"])

    # ── Day of week ──────────────────────────────────────────────────────────
    dow_map: dict[str, dict] = {d: {"count": 0, **{ak: 0 for ak in APP_KEYS}} for d in DAY_NAMES}
    for doc in all_docs:
        date_str = (doc.get("date") or "")[:10]
        try:
            idx = datetime.strptime(date_str, "%Y-%m-%d").weekday()
            day_name = DAY_NAMES[idx]
        except (ValueError, IndexError):
            continue
        ak = doc.get("app") or ""
        dow_map[day_name]["count"] += 1
        if ak in APP_KEYS:
            dow_map[day_name][ak] += 1

    by_day_of_week = [{"day": d, **dow_map[d]} for d in DAY_NAMES]

    # ── Score distribution ────────────────────────────────────────────────────
    SCORE_BUCKETS = [("0–4", 0, 4), ("4–6", 4, 6), ("6–7", 6, 7), ("7–8", 7, 8), ("8–9", 8, 9), ("9–10", 9, 11)]
    sdist: dict[str, dict] = {label: {"count": 0, **{ak: 0 for ak in APP_KEYS}} for label, _, _ in SCORE_BUCKETS}
    for doc in all_docs:
        score = doc.get("grading", {}).get("final_score_10")
        if score is None:
            continue
        ak = doc.get("app") or ""
        for label, lo, hi in SCORE_BUCKETS:
            if lo <= score < hi:
                sdist[label]["count"] += 1
                if ak in APP_KEYS:
                    sdist[label][ak] += 1
                break

    score_distribution = [{"range": label, **sdist[label]} for label, _, _ in SCORE_BUCKETS]

    # ── App totals ────────────────────────────────────────────────────────────
    # Luôn tính "by_app" trên CẢ 2 collection, bất kể app_filter — filter chỉ nên thu hẹp
    # time_series/by_agent/by_day_of_week/score_distribution, không nên làm app kia hiện "0"
    # (trước đây app_filter thu hẹp cả col_names khiến app không được chọn luôn ra 0).
    by_app: dict[str, int] = {ak: 0 for ak in APP_KEYS}
    all_scores: list[float] = []
    if app_filter:
        by_app_docs = list(get_db()[col].find(query, {"app": 1}) for col in ALL_GRADING_COLLECTIONS)
        by_app_docs = [d for sub in by_app_docs for d in sub]
    else:
        by_app_docs = all_docs
    for doc in by_app_docs:
        ak = doc.get("app") or ""
        if ak in APP_KEYS:
            by_app[ak] += 1
    for doc in all_docs:
        sc = doc.get("grading", {}).get("final_score_10")
        if sc is not None:
            all_scores.append(sc)

    # ── Real Crisp total (crawl_stats) ──────────────────────────────────────────
    # Số conversation THẬT trên Crisp (trước khi lọc/chấm) cho khoảng ngày này — dùng để đối
    # chiếu với "total" (số đã chấm). KHÔNG tách được theo app (1 inbox Crisp chung cho mọi
    # app, phân loại app chỉ xảy ra lúc chấm) — chỉ có tổng gộp.
    crawl_stats_docs = get_crawl_stats(date_from or None, date_to or None)
    real_total = sum(d.get("total_fetched", 0) for d in crawl_stats_docs) if crawl_stats_docs else None

    return {
        "total": len(all_docs),
        "real_total": real_total,
        "avg_score": round(sum(all_scores) / len(all_scores), 2) if all_scores else None,
        "by_app": by_app,
        "time_series": time_series,
        "by_agent": by_agent,
        "by_day_of_week": by_day_of_week,
        "score_distribution": score_distribution,
    }


# ---------------------------------------------------------------------------
# Routes — Day × Hour heatmap  (uses sumtag.end_session timestamps)
# ---------------------------------------------------------------------------

@app.get("/api/heatmap", dependencies=[Depends(require_manager_or_admin)])
def get_heatmap(
    app_filter: str = Query("", alias="app"),
    date_from:  str = Query(""),
    date_to:    str = Query(""),
):
    from datetime import datetime as _dt

    db = get_db()

    # Date filter on sumtag.crawl_date
    sumtag_q: dict[str, Any] = {"end_session": {"$ne": None}}
    if date_from and date_to:
        sumtag_q["crawl_date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        sumtag_q["crawl_date"] = {"$gte": date_from}
    elif date_to:
        sumtag_q["crawl_date"] = {"$lte": date_to}

    # App filter: join via session_id from grading collection
    if app_filter:
        col_name = _app_to_col(app_filter)
        if col_name:
            grading_q: dict[str, Any] = {}
            if date_from and date_to:
                grading_q["date"] = {"$gte": date_from, "$lte": date_to}
            elif date_from:
                grading_q["date"] = {"$gte": date_from}
            elif date_to:
                grading_q["date"] = {"$lte": date_to}
            grading_ids = db[col_name].distinct("session_id", grading_q)
            if not grading_ids:
                return {"grid": [[0] * 24 for _ in range(7)], "total": 0}
            sumtag_q["session_id"] = {"$in": grading_ids}

    docs = list(db["sumtag"].find(sumtag_q, {"end_session": 1}))

    grid = [[0] * 24 for _ in range(7)]   # grid[day 0=Mon][hour 0-23]
    for doc in docs:
        es = doc.get("end_session") or ""
        try:
            dt = _dt.strptime(str(es)[:19], "%Y-%m-%d %H:%M:%S")
            grid[dt.weekday()][dt.hour] += 1
        except (ValueError, TypeError):
            continue

    return {"grid": grid, "total": sum(c for row in grid for c in row)}


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
