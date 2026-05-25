"""
QA Support Analyzer — MCP Server

Tools:
  qa_overview        — tổng quan điểm theo khoảng ngày + LLM summary
  qa_by_date         — chi tiết từng chat trong ngày, có summary + tags từ sumtag
  qa_by_agent        — điểm và phân tích theo agent
  qa_regrade         — chấm lại 1 chat với prompt tùy chọn
  qa_prompt_get      — lấy prompt đang active
  qa_prompt_update   — lưu version prompt mới vào DB
  qa_prompt_suggest  — LLM gợi ý cải thiện prompt từ feedback

Tham số app: "" = cả DECO lẫn SearchPie, "DECO" hoặc "SearchPie" để lọc.

Chạy:
  cd support_analyzer
  source venv/bin/activate
  python -m mcp_server.server
"""

import os
import sys
import requests
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from database.tunnel import ensure_tunnel
from database.deco_chat import (
    get_chats_by_date_range,
    get_chats_by_date,
    get_chats_by_operator,
    get_chat,
    upsert_chat,
)
from database.sumtag import (
    get_by_date       as get_sumtags_by_date,
    get_by_date_range as get_sumtags_by_date_range,
    get_by_operator   as get_sumtags_by_operator,
)
from database.prompts import get_active_prompt, get_prompt_content, save_prompt
from analyzer_v2 import _parse_and_cap, GRADING_CRITERIA

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

ensure_tunnel()


# ---------------------------------------------------------------------------
# Helper: LLM call
# ---------------------------------------------------------------------------

def _llm(system: str, user: str, max_tokens: int = 2048) -> str:
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user}],
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Helper: stats
# ---------------------------------------------------------------------------

_KEY_MAP = [
    "greetings", "grammar", "communication", "listening", "tone_pace", "empathy",
    "enthusiastic", "probing", "solution", "proactiveness", "transferring",
    "resources", "extra_mile", "review_asking",
]

_CAPS = {
    "greetings": 0.25, "grammar": 1.25, "communication": 2.0, "listening": 1.5,
    "tone_pace": 0.75, "empathy": 0.75, "enthusiastic": 1.5, "probing": 1.5,
    "solution": 3.0, "proactiveness": 2.0, "transferring": 2.0, "resources": 0.5,
    "extra_mile": 1.5, "review_asking": 1.5,
}


def _max_score(key: str) -> float:
    return _CAPS.get(key, 0)


def _compute_stats(chats: list[dict]) -> dict:
    if not chats:
        return {"total": 0, "graded": 0}

    scored = [c for c in chats if c.get("grading")]
    scores = [c["grading"]["final_score_10"] for c in scored]
    avg = round(sum(scores) / len(scores), 2) if scores else 0

    by_agent: dict[str, list[float]] = {}
    for c in scored:
        by_agent.setdefault(c["primary_operator"], []).append(c["grading"]["final_score_10"])
    agent_stats = {
        agent: {"avg": round(sum(s) / len(s), 2), "count": len(s)}
        for agent, s in sorted(by_agent.items())
    }

    by_app: dict[str, list[float]] = {}
    for c in scored:
        by_app.setdefault(c.get("app", "Unknown"), []).append(c["grading"]["final_score_10"])
    app_stats = {
        a: {"avg": round(sum(s) / len(s), 2), "count": len(s)}
        for a, s in sorted(by_app.items())
    }

    deductions: dict[str, int] = {}
    for c in scored:
        criteria = c["grading"].get("criteria", {})
        for key in _KEY_MAP:
            if criteria.get(key, {}).get("score", 999) < _max_score(key):
                deductions[key] = deductions.get(key, 0) + 1
    top_deductions = sorted(deductions.items(), key=lambda x: -x[1])[:5]

    return {
        "total":          len(chats),
        "graded":         len(scored),
        "avg_score":      avg,
        "min_score":      round(min(scores), 2) if scores else 0,
        "max_score":      round(max(scores), 2) if scores else 0,
        "by_agent":       agent_stats,
        "by_app":         app_stats,
        "top_deductions": [{"criterion": k, "count": v} for k, v in top_deductions],
    }


def _top_tags(sumtags: list[dict], n: int = 10) -> list[tuple[str, int]]:
    counter: Counter = Counter()
    for doc in sumtags:
        for tag in doc.get("tags") or []:
            counter[tag] += 1
    return counter.most_common(n)


def _app_filter(app: str) -> str | None:
    return app.strip() or None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def qa_overview(from_date: str, to_date: str, app: str = "", summarize: bool = True) -> str:
    """
    Tổng quan điểm QA theo khoảng ngày.
    from_date / to_date: YYYY-MM-DD.
    app: "" (cả DECO + SearchPie), "DECO", hoặc "SearchPie".
    summarize=True: thêm LLM nhận xét tổng quan bằng tiếng Việt.
    """
    af = _app_filter(app)
    chats = get_chats_by_date_range(from_date, to_date, app=af)
    if not chats:
        label = f" [{app}]" if app else ""
        return f"Không có dữ liệu từ {from_date} đến {to_date}{label}."

    stats = _compute_stats(chats)
    app_label = f" [{app}]" if app else " [DECO + SearchPie]"

    lines = [
        f"📊 Tổng quan {from_date} → {to_date}{app_label}",
        f"Tổng: {stats['total']} chat  |  Đã chấm: {stats['graded']}",
        f"Điểm TB: {stats['avg_score']}/10  |  Min: {stats['min_score']}  |  Max: {stats['max_score']}",
    ]

    if not af and len(stats["by_app"]) > 1:
        lines.append("\nTheo app:")
        for a, s in stats["by_app"].items():
            lines.append(f"  • {a}: {s['avg']}/10 ({s['count']} chat)")

    lines.append("\nTheo agent:")
    for agent, s in stats["by_agent"].items():
        lines.append(f"  • {agent}: {s['avg']}/10 ({s['count']} chat)")

    lines.append("\nTiêu chí bị trừ nhiều nhất:")
    for d in stats["top_deductions"]:
        lines.append(f"  • {d['criterion']}: {d['count']} lần")

    sumtags = get_sumtags_by_date_range(from_date, to_date, app=af)
    top_tags = _top_tags(sumtags)
    if top_tags:
        lines.append("\nTop tags:")
        for tag, cnt in top_tags:
            lines.append(f"  • #{tag}: {cnt}")

    result = "\n".join(lines)

    if summarize and OPENROUTER_API_KEY:
        summary = _llm(
            "Bạn là QA lead, hãy nhận xét ngắn gọn (5-7 câu) về chất lượng support team dựa trên số liệu sau.",
            result,
        )
        result += f"\n\n💬 Nhận xét:\n{summary}"

    return result


@mcp.tool()
def qa_by_date(date: str, app: str = "") -> str:
    """
    Chi tiết điểm từng chat trong một ngày (YYYY-MM-DD).
    app: "" (cả DECO + SearchPie), "DECO", hoặc "SearchPie".
    """
    af = _app_filter(app)
    chats = get_chats_by_date(date, app=af)
    if not chats:
        label = f" [{app}]" if app else ""
        return f"Không có chat nào ngày {date}{label}."

    sumtags = get_sumtags_by_date(date, app=af)
    st_map = {s["session_id"]: s for s in sumtags}

    app_label = f" [{app}]" if app else ""
    lines = [f"📅 {date}{app_label} — {len(chats)} chat(s)\n"]

    for c in sorted(chats, key=lambda x: (x.get("app", ""), x.get("primary_operator", ""))):
        g = c.get("grading", {})
        score = g.get("final_score_10", "?")
        resolved = "✅" if c.get("is_resolved") else "🔄"
        crisp_url = (
            c.get("crisp_url")
            or f"https://app.crisp.chat/website/{c['website_id']}/inbox/{c['session_id']}"
        )

        st = st_map.get(c["session_id"])
        tags_str = "  " + " ".join(f"#{t}" for t in (st or {}).get("tags") or [])
        summary = (st or {}).get("summary") or g.get("overall_summary") or ""
        time_str = ""
        if st and st.get("start") and st.get("end"):
            time_str = f"  🕐 {st['start']} → {st['end']}  ({st.get('msg_count', '?')} tin)\n"

        block = (
            f"  [{score}/10] {resolved} {c['primary_operator']} | {c['app']} | {c['customer']}\n"
            + time_str
            + (f"{tags_str}\n" if tags_str.strip() else "")
            + (f"  {summary[:220]}\n" if summary else "")
            + f"  🔗 {crisp_url}"
        )
        lines.append(block)

    return "\n".join(lines)


@mcp.tool()
def qa_by_agent(agent: str, from_date: str = "", to_date: str = "", app: str = "") -> str:
    """
    Điểm và phân tích chi tiết theo agent.
    from_date / to_date: YYYY-MM-DD (tùy chọn).
    app: "" (cả DECO + SearchPie), "DECO", hoặc "SearchPie".
    """
    af = _app_filter(app)
    chats = (
        get_chats_by_date_range(from_date, to_date, operator=agent, app=af)
        if from_date and to_date
        else get_chats_by_operator(agent, app=af)
    )
    if not chats:
        label = f" [{app}]" if app else ""
        return f"Không có dữ liệu cho agent '{agent}'{label}."

    stats = _compute_stats(chats)

    sumtags = (
        get_sumtags_by_date_range(from_date, to_date, operator=agent, app=af)
        if from_date and to_date
        else get_sumtags_by_operator(agent, app=af)
    )
    top_tags = _top_tags(sumtags, n=8)

    app_label = f" [{app}]" if app else ""
    lines = [f"👤 {agent}{app_label}  |  {stats['total']} chat  |  TB: {stats['avg_score']}/10\n"]

    if not af and len(stats["by_app"]) > 1:
        lines.append("Theo app:")
        for a, s in stats["by_app"].items():
            lines.append(f"  • {a}: {s['avg']}/10 ({s['count']} chat)")
        lines.append("")

    lines.append("Tiêu chí bị trừ:")
    for d in stats["top_deductions"]:
        lines.append(f"  • {d['criterion']}: {d['count']} lần")

    if top_tags:
        lines.append("\nTop tags:")
        for tag, cnt in top_tags:
            lines.append(f"  • #{tag}: {cnt}")

    lines.append("\nCác chat gần nhất:")
    for c in sorted(chats, key=lambda x: x.get("date", ""), reverse=True)[:10]:
        g = c.get("grading", {})
        crisp_url = (
            c.get("crisp_url")
            or f"https://app.crisp.chat/website/{c['website_id']}/inbox/{c['session_id']}"
        )
        lines.append(
            f"  [{c['date']}] {g.get('final_score_10', '?')}/10 — {c.get('app', '')} | {c.get('customer', '')} | {crisp_url}"
        )

    if OPENROUTER_API_KEY:
        feedback = _llm(
            f"Bạn là QA lead, hãy nhận xét ngắn gọn (3-5 câu) về điểm mạnh và điểm cần cải thiện của agent {agent} dựa trên số liệu.",
            "\n".join(lines),
        )
        lines.append(f"\n💬 Nhận xét cá nhân:\n{feedback}")

    return "\n".join(lines)


@mcp.tool()
def qa_regrade(session_id: str, app: str = "", custom_prompt: str = "") -> str:
    """
    Chấm lại một chat theo session_id.
    app: "DECO" hoặc "SearchPie" (tùy chọn, để tìm nhanh hơn).
    custom_prompt: nếu để trống, dùng prompt active từ DB.
    """
    af = _app_filter(app)
    chat = get_chat(session_id, app=af)
    if not chat:
        return f"Không tìm thấy session '{session_id}'."

    prompt = custom_prompt or get_prompt_content() or GRADING_CRITERIA

    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL, "max_tokens": 4096,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user",   "content": f"Chấm đoạn chat sau:\n\n{chat['transcript']}"},
                ],
            },
            timeout=90,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        grading = _parse_and_cap(raw)
    except Exception as e:
        return f"❌ Lỗi khi chấm: {e}"

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
        tags=chat.get("tags"),
        crisp_url=chat.get("crisp_url"),
    )

    return (
        f"✅ Chấm lại xong — {grading['final_score_10']}/10\n"
        f"App: {chat['app']} | Agent: {chat['primary_operator']}\n"
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
            f"Lý do: {doc.get('reason', 'N/A')}\n"
            f"Ngày tạo: {doc['created_at']}\n\n"
            f"{doc['content']}"
        )
    return f"[Chưa có prompt trong DB — đang dùng mặc định]\n\n{GRADING_CRITERIA}"


@mcp.tool()
def qa_prompt_update(new_prompt: str, reason: str = "") -> str:
    """
    Lưu version prompt mới vào DB, kích hoạt ngay.
    new_prompt: nội dung GRADING_CRITERIA mới.
    reason: lý do thay đổi.
    """
    doc = save_prompt(new_prompt, reason)
    return (
        f"✅ Đã lưu prompt version {doc['version']}\n"
        f"Lý do: {reason or 'Không ghi chú'}\n"
        f"Prompt mới đã được kích hoạt."
    )


@mcp.tool()
def qa_prompt_suggest(feedback: str, from_date: str = "", to_date: str = "", app: str = "") -> str:
    """
    LLM phân tích các chat gần đây và đề xuất chỉnh sửa prompt.
    feedback: mô tả vấn đề (ví dụ: "model đang chấm quá nghiêm ở tiêu chí greeting").
    from_date / to_date: lấy mẫu chat để phân tích (tùy chọn).
    app: "" (cả hai), "DECO", hoặc "SearchPie".
    """
    if not OPENROUTER_API_KEY:
        return "❌ Thiếu OPENROUTER_API_KEY."

    af = _app_filter(app)
    current_prompt = get_prompt_content() or GRADING_CRITERIA

    sample_context = ""
    if from_date and to_date:
        chats = get_chats_by_date_range(from_date, to_date, app=af)[:5]
        if chats:
            sample_context = "\n\nCÁC CHAT MẪU:\n"
            for c in chats:
                g = c.get("grading", {})
                sample_context += (
                    f"\n--- {c['primary_operator']} | {c['app']} | {g.get('final_score_10')}đ ---\n"
                    f"{c['transcript'][:800]}\n"
                    "Justification: "
                    + "; ".join(
                        f"{k}: {v.get('justification', '')[:80]}"
                        for k, v in list(g.get("criteria", {}).items())[:4]
                    )
                )

    system = (
        "Bạn là chuyên gia thiết kế QA prompt cho hệ thống chấm điểm support chat. "
        "Hãy đề xuất chỉnh sửa cụ thể cho prompt hiện tại dựa trên feedback nhận được. "
        "Trả về: (1) Phân tích vấn đề, (2) Đoạn text cần sửa trong prompt, "
        "(3) Đề xuất thay thế cụ thể, (4) Giải thích tại sao thay đổi này giúp ích. "
        "Trả lời hoàn toàn bằng tiếng Việt."
    )
    user = f"FEEDBACK: {feedback}\n\nPROMPT HIỆN TẠI:\n{current_prompt}{sample_context}"

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
        from pyngrok import ngrok as _ngrok
        tunnel = _ngrok.connect(a.port, bind_tls=True)
        public_url = tunnel.public_url
        print(f"🌐 MCP server  : http://{a.host}:{a.port}/mcp")
        print(f"🔗 Ngrok URL   : {public_url}/mcp")
        print(f"👉 Thêm vào Claude.ai connector: {public_url}/mcp")
        uvicorn.run(mcp.streamable_http_app(), host=a.host, port=a.port)
    else:
        mcp.run()
