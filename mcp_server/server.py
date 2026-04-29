"""
QA Support Analyzer — MCP Server

Tools:
  qa_overview        — tổng quan điểm theo khoảng ngày + LLM summary
  qa_by_date         — chi tiết từng chat trong ngày
  qa_by_agent        — điểm và phân tích theo agent
  qa_regrade         — chấm lại 1 chat với prompt tùy chọn
  qa_prompt_get      — lấy prompt đang active
  qa_prompt_update   — lưu version prompt mới vào DB
  qa_prompt_suggest  — LLM gợi ý cải thiện prompt từ feedback

Chạy:
  cd support_analyzer
  source venv/bin/activate
  python -m mcp_server.server
"""

import os
import sys
import json
import requests

# Đảm bảo import được các module trong project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from database.tunnel import ensure_tunnel
from database.deco_chat import get_chats_by_date_range, get_chats_by_date, get_chats_by_operator, get_chat
from database.prompts import get_active_prompt, get_prompt_content, save_prompt, list_prompt_versions
from analyzer_v2 import grade_chat, _parse_and_cap, GRADING_CRITERIA
from database.deco_chat import upsert_chat

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

_HTTP_PORT = int(os.getenv("MCP_PORT", "8765"))

mcp = FastMCP(
    "qa-analyzer",
    transport_security=TransportSecuritySettings(
        allowed_hosts=[f"localhost:{_HTTP_PORT}", f"127.0.0.1:{_HTTP_PORT}"],
        allowed_origins=["https://claude.ai"],
    ),
)

# Mở tunnel một lần khi server khởi động
ensure_tunnel()


# ---------------------------------------------------------------------------
# Helper: gọi LLM
# ---------------------------------------------------------------------------

def _llm(system: str, user: str, max_tokens: int = 2048) -> str:
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system},
                           {"role": "user",   "content": user}]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Helper: tính stats từ danh sách chats
# ---------------------------------------------------------------------------

_KEY_MAP = ["greetings", "grammar", "communication", "listening", "tone_pace", "empathy",
            "enthusiastic", "probing", "solution", "proactiveness", "transferring",
            "resources", "extra_mile", "review_asking"]

def _compute_stats(chats: list[dict]) -> dict:
    if not chats:
        return {"total": 0}

    scores = [c["grading"]["final_score_10"] for c in chats if c.get("grading")]
    avg = round(sum(scores) / len(scores), 2) if scores else 0

    # Phân tích theo agent
    by_agent: dict[str, list[float]] = {}
    for c in chats:
        if c.get("grading"):
            by_agent.setdefault(c["primary_operator"], []).append(c["grading"]["final_score_10"])
    agent_stats = {
        agent: {"avg": round(sum(s) / len(s), 2), "count": len(s)}
        for agent, s in sorted(by_agent.items())
    }

    # Tiêu chí bị trừ nhiều nhất
    deductions: dict[str, int] = {}
    for c in chats:
        criteria = c.get("grading", {}).get("criteria", {})
        for key in _KEY_MAP:
            if criteria.get(key, {}).get("score", 999) < _max_score(key):
                deductions[key] = deductions.get(key, 0) + 1
    top_deductions = sorted(deductions.items(), key=lambda x: -x[1])[:5]

    return {
        "total":          len(chats),
        "avg_score":      avg,
        "min_score":      round(min(scores), 2) if scores else 0,
        "max_score":      round(max(scores), 2) if scores else 0,
        "by_agent":       agent_stats,
        "top_deductions": [{"criterion": k, "count": v} for k, v in top_deductions],
    }


_CAPS = {"greetings": 0.25, "grammar": 1.25, "communication": 2.0, "listening": 1.5,
         "tone_pace": 0.75, "empathy": 0.75, "enthusiastic": 1.5, "probing": 1.5,
         "solution": 3.0, "proactiveness": 2.0, "transferring": 2.0, "resources": 0.5,
         "extra_mile": 1.5, "review_asking": 1.5}

def _max_score(key: str) -> float:
    return _CAPS.get(key, 0)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def qa_overview(from_date: str, to_date: str, summarize: bool = True) -> str:
    """
    Tổng quan điểm QA theo khoảng ngày.
    from_date / to_date: định dạng YYYY-MM-DD.
    summarize=True: thêm LLM nhận xét tổng quan bằng tiếng Việt.
    """
    chats = get_chats_by_date_range(from_date, to_date)
    if not chats:
        return f"Không có dữ liệu từ {from_date} đến {to_date}."

    stats = _compute_stats(chats)
    result = (
        f"📊 Tổng quan {from_date} → {to_date}\n"
        f"Tổng số chat: {stats['total']}\n"
        f"Điểm TB: {stats['avg_score']}/10  |  Min: {stats['min_score']}  |  Max: {stats['max_score']}\n\n"
        f"Theo agent:\n"
    )
    for agent, s in stats["by_agent"].items():
        result += f"  • {agent}: {s['avg']}/10 ({s['count']} chat)\n"

    result += "\nTiêu chí bị trừ nhiều nhất:\n"
    for d in stats["top_deductions"]:
        result += f"  • {d['criterion']}: {d['count']} lần\n"

    if summarize and OPENROUTER_API_KEY:
        summary = _llm(
            "Bạn là QA lead, hãy nhận xét ngắn gọn (5-7 câu) về chất lượng support team dựa trên số liệu sau.",
            result
        )
        result += f"\n💬 Nhận xét:\n{summary}"

    return result


@mcp.tool()
def qa_by_date(date: str) -> str:
    """
    Chi tiết điểm từng chat trong một ngày (YYYY-MM-DD).
    """
    chats = get_chats_by_date(date)
    if not chats:
        return f"Không có chat nào ngày {date}."

    lines = [f"📅 {date} — {len(chats)} chat(s)\n"]
    for c in sorted(chats, key=lambda x: x.get("primary_operator", "")):
        g = c.get("grading", {})
        lines.append(
            f"  [{g.get('final_score_10', '?')}/10] {c['primary_operator']} | {c['app']} | {c['customer']}\n"
            f"    {g.get('overall_summary', '')}\n"
            f"    🔗 {c.get('crisp_url', '')}"
        )
    return "\n".join(lines)


@mcp.tool()
def qa_by_agent(agent: str, from_date: str = "", to_date: str = "") -> str:
    """
    Điểm và phân tích chi tiết theo agent.
    from_date / to_date tùy chọn (YYYY-MM-DD).
    """
    if from_date and to_date:
        chats = get_chats_by_date_range(from_date, to_date, operator=agent)
    else:
        chats = get_chats_by_operator(agent)

    if not chats:
        return f"Không có dữ liệu cho agent '{agent}'."

    stats = _compute_stats(chats)
    lines = [
        f"👤 {agent}  |  {stats['total']} chat  |  TB: {stats['avg_score']}/10\n",
        "Tiêu chí bị trừ:\n",
    ]
    for d in stats["top_deductions"]:
        lines.append(f"  • {d['criterion']}: {d['count']} lần")

    lines.append("\nCác chat gần nhất:")
    for c in sorted(chats, key=lambda x: x.get("date", ""), reverse=True)[:10]:
        g = c.get("grading", {})
        lines.append(
            f"  [{c['date']}] {g.get('final_score_10', '?')}/10 — {c.get('customer', '')} | {c.get('crisp_url', '')}"
        )

    # LLM nhận xét riêng cho agent
    if OPENROUTER_API_KEY:
        feedback = _llm(
            f"Bạn là QA lead, hãy nhận xét ngắn gọn (3-5 câu) về điểm mạnh và điểm cần cải thiện của agent {agent} dựa trên số liệu.",
            "\n".join(lines)
        )
        lines.append(f"\n💬 Nhận xét cá nhân:\n{feedback}")

    return "\n".join(lines)


@mcp.tool()
def qa_regrade(session_id: str, custom_prompt: str = "") -> str:
    """
    Chấm lại một chat theo session_id.
    custom_prompt: nếu để trống, dùng prompt đang active trong DB (hoặc mặc định).
    """
    chat = get_chat(session_id)
    if not chat:
        return f"Không tìm thấy session '{session_id}'."

    prompt = custom_prompt or get_prompt_content() or GRADING_CRITERIA

    # Gọi API với prompt tùy chỉnh
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "max_tokens": 4096,
                  "response_format": {"type": "json_object"},
                  "messages": [
                      {"role": "system", "content": prompt},
                      {"role": "user",   "content": f"Chấm đoạn chat sau:\n\n{chat['transcript']}"},
                  ]},
            timeout=90,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        grading = _parse_and_cap(raw)
    except Exception as e:
        return f"❌ Lỗi khi chấm: {e}"

    # Lưu lại vào DB
    upsert_chat(
        session_id=chat["session_id"],
        website_id=chat["website_id"],
        date=chat["date"],
        app=chat["app"],
        customer=chat["customer"],
        primary_operator=chat["primary_operator"],
        is_resolved=chat["is_resolved"],
        transcript=chat["transcript"],
        grading=grading,
        summary=chat.get("summary"),
        crisp_url=chat.get("crisp_url"),
    )

    return (
        f"✅ Chấm lại xong — {grading['final_score_10']}/10\n"
        f"Nhận xét: {grading.get('overall_summary', '')}\n"
        f"(Đã lưu vào DB)"
    )


@mcp.tool()
def qa_prompt_get() -> str:
    """
    Lấy prompt QA đang active từ DB.
    Nếu chưa có trong DB, trả về prompt mặc định từ analyzer_v2.
    """
    doc = get_active_prompt()
    if doc:
        return (
            f"📝 Prompt version {doc['version']} (active)\n"
            f"Lý do cập nhật: {doc.get('reason', 'N/A')}\n"
            f"Ngày tạo: {doc['created_at']}\n\n"
            f"{doc['content']}"
        )
    return f"[Chưa có prompt trong DB — đang dùng mặc định]\n\n{GRADING_CRITERIA}"


@mcp.tool()
def qa_prompt_update(new_prompt: str, reason: str = "") -> str:
    """
    Lưu version prompt mới vào DB, kích hoạt ngay.
    new_prompt: nội dung GRADING_CRITERIA mới.
    reason: lý do thay đổi (để track lịch sử).
    """
    doc = save_prompt(new_prompt, reason)
    return (
        f"✅ Đã lưu prompt version {doc['version']}\n"
        f"Lý do: {reason or 'Không ghi chú'}\n"
        f"Prompt mới đã được kích hoạt."
    )


@mcp.tool()
def qa_prompt_suggest(feedback: str, from_date: str = "", to_date: str = "") -> str:
    """
    LLM phân tích các chat gần đây và đề xuất chỉnh sửa prompt dựa trên feedback.
    feedback: mô tả vấn đề (ví dụ: "model đang chấm quá nghiêm ở tiêu chí greeting").
    from_date / to_date: lấy mẫu chat trong khoảng ngày để phân tích (tùy chọn).
    """
    current_prompt = get_prompt_content() or GRADING_CRITERIA

    # Lấy vài ví dụ chat gần đây để LLM phân tích
    sample_context = ""
    if from_date and to_date:
        chats = get_chats_by_date_range(from_date, to_date)[:5]
        if chats:
            sample_context = "\n\nCÁC CHAT MẪU GẦN ĐÂY:\n"
            for c in chats:
                g = c.get("grading", {})
                sample_context += (
                    f"\n--- {c['primary_operator']} | {g.get('final_score_10')}đ ---\n"
                    f"{c['transcript'][:800]}\n"
                    f"Justification nổi bật: "
                    + "; ".join(
                        f"{k}: {v.get('justification', '')[:80]}"
                        for k, v in list(g.get("criteria", {}).items())[:4]
                    )
                )

    system = (
        "Bạn là chuyên gia thiết kế QA prompt cho hệ thống chấm điểm support chat. "
        "Hãy đề xuất chỉnh sửa cụ thể cho prompt hiện tại dựa trên feedback nhận được. "
        "Trả về: (1) Phân tích vấn đề, (2) Đoạn text cần sửa trong prompt, "
        "(3) Đề xuất thay thế cụ thể, (4) Giải thích tại sao thay đổi này giúp ích."
        "Trả lời hoàn toàn bằng tiếng Việt."
    )
    user = (
        f"FEEDBACK: {feedback}\n\n"
        f"PROMPT HIỆN TẠI:\n{current_prompt}"
        f"{sample_context}"
    )

    if not OPENROUTER_API_KEY:
        return "❌ Thiếu OPENROUTER_API_KEY."

    suggestion = _llm(system, user, max_tokens=3000)
    return f"💡 Gợi ý chỉnh sửa prompt:\n\n{suggestion}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse as _ap
    p = _ap.ArgumentParser()
    p.add_argument("--http", action="store_true", help="Run as HTTP server (for claude.ai connector)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="0.0.0.0")
    a = p.parse_args()

    if a.http:
        import uvicorn
        print(f"🌐 Starting HTTP MCP server on http://{a.host}:{a.port}/mcp")
        uvicorn.run(mcp.streamable_http_app(), host=a.host, port=a.port)
    else:
        mcp.run()  # stdio mode cho Claude Code CLI
