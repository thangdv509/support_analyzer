"""
main.py — upgraded entry point for the QA analyzer.

Extends analyzer_v2 by saving graded chats to MongoDB (deco_chat collection)
in addition to Google Sheets and local JSON.

Google Sheets behaviour:
- All dates in one run → one sheet named by run timestamp (e.g. "14:35")
- Never touches other existing sheets
- Agent summary table at the bottom (same as original)

Usage:
    python3 main.py                        # grade today
    python3 main.py --date 2026-04-12      # grade specific date
    python3 main.py --from 2026-04-07 --to 2026-04-13
    python3 main.py --regrade qa_report_20260412.json
    python3 main.py --no-mongo             # skip MongoDB (no tunnel needed)
"""

import os
import json
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

import requests

from analyzer_v2 import (
    fetch_chats,
    load_few_shot_examples,
    _grade_one,
    _fmt_elapsed,
    GOOGLE_SHEET_ID,
    GOOGLE_CREDENTIALS_PATH,
    OPENROUTER_API_KEY,
    MODEL,
    _SCORE_CAPS,
)

from database.tunnel import ensure_tunnel
from database.deco_chat import upsert_many
from database.connection import get_db
from database.sumtag import append_segment as sumtag_append_segment

load_dotenv()

# ---------------------------------------------------------------------------
# Summary generation (same prompt/logic as crawl.py)
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT = (
    "Bạn là trợ lý AI chuyên tóm tắt các cuộc hội thoại hỗ trợ khách hàng. "
    "Phân tích cuộc hội thoại và tạo bản tóm tắt rõ ràng, súc tích bằng tiếng Việt, bao gồm: "
    "Vấn đề hoặc câu hỏi chính của khách hàng (pain point, yêu cầu, lỗi gặp phải); "
    "Bối cảnh và thông tin liên quan từ khách hàng (thông tin nền, làm rõ, ví dụ cụ thể); "
    "Hành động và giải pháp mà agent đã thực hiện trong cuộc hội thoại; "
    "Quyết định hoặc thỏa thuận đã đạt được giữa khách hàng và agent; "
    "Thái độ và cảm xúc nổi bật của khách hàng (ví dụ: bức xúc, hài lòng, trung lập). "
    "Trình bày dưới dạng danh sách bullet point, ngôn ngữ chuyên nghiệp, phù hợp để theo dõi nội bộ hoặc bàn giao ca."
    "\n\nCuối cùng, trả về một JSON block theo đúng định dạng sau:\n"
    '```json\n{"tags": ["tag1", "tag2", "tag3"]}\n```\n'
    "3 tags phải ngắn gọn (2-4 từ tiếng Anh), là các nhãn chủ đề cụ thể nhất mô tả cuộc hội thoại này."
)


def _generate_summary_and_tags(transcript: str) -> tuple[str | None, list[str]]:
    """Generate bullet-point summary + 3 topic tags in one LLM call.
    Returns (summary_text, tags).
    """
    if not OPENROUTER_API_KEY:
        return None, []
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "messages": [
                {"role": "system", "content": _SUMMARY_PROMPT},
                {"role": "user",   "content": transcript},
            ]},
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()

        tags: list[str] = []
        summary_text = raw
        if "```json" in raw:
            parts = raw.split("```json")
            summary_text = parts[0].strip()
            try:
                tags_raw = parts[1].split("```")[0].strip()
                tags = json.loads(tags_raw).get("tags", [])
            except Exception:
                pass

        return summary_text, tags
    except Exception as e:
        print(f"    ⚠️  Summary generation failed: {e}")
        return None, []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KEY_MAP = ["greetings", "grammar", "communication", "listening", "tone_pace", "empathy",
            "enthusiastic", "probing", "solution", "proactiveness", "transferring",
            "resources", "extra_mile", "review_asking"]
_CAPS = {k: _SCORE_CAPS[k] for k in _KEY_MAP}
_MAX_SCORES = [0, 0, 0, 0, 0, 0.25, 1.25, 2.0, 1.5, 0.75, 0.75, 1.5, 1.5, 3.0, 2.0, 2.0, 0.5, 1.5, 1.5, 0]

_HEADERS = ["Convo Date", "Chat URL", "App", "Support", "Rating (/10)",
            "Greeting (0.25)", "Grammar (1.25)", "Concise (2.0)", "Listening (1.5)",
            "Tone/Pace (0.75)", "Empathy (0.75)", "Enthusiastic (1.5)", "Probing (1.5)",
            "Solution (3.0)", "Pro-active (2.0)", "Transfer (2.0)", "Resources (0.5)",
            "Extra Mile (1.5)", "Review (1.5)", "Comments", "Resolved"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_color(h):
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _score(criteria: dict, key: str) -> float:
    return min(float(criteria.get(key, {}).get("score", 0)), _CAPS.get(key, 9999))


# ---------------------------------------------------------------------------
# Grade one date, return results (also saves local JSON)
# ---------------------------------------------------------------------------

def _already_saved_keys() -> set[tuple[str, str]]:
    """Lấy tất cả (session_id, date) đã có trong MongoDB."""
    try:
        ensure_tunnel()
        col = get_db()["deco_chat"]
        return {(doc["session_id"], doc["date"]) for doc in col.find({}, {"session_id": 1, "date": 1})}
    except Exception:
        return set()


def _grade_date(chats: list[dict], date_str: str, suffix: str = "") -> list[dict]:
    if not chats:
        print(f"  No chats found for {date_str}.")
        return []

    print(f"⚖️  Grading {len(chats)} chats for {date_str} (parallel)...")
    args_list = [(i, len(chats), chat) for i, chat in enumerate(chats, 1)]
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_grade_one, a): a for a in args_list}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                results.append(r)

    if results:
        date_nodash = date_str.replace("-", "")
        output_json = f"qa_report_{date_nodash}{suffix}.json"
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON saved: {output_json}")

    return results


# ---------------------------------------------------------------------------
# Google Sheets export — all results in one sheet, summary at bottom
# ---------------------------------------------------------------------------

def _export_to_gsheet(all_results: list[dict], sheet_name: str):
    if not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        print("❌ Missing GOOGLE_SHEET_ID or GOOGLE_CREDENTIALS_PATH in .env")
        return

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

    # Always create a new sheet (name is timestamp so it won't collide)
    needed_rows = len(all_results) + 50  # header + data + blank + summary buffer
    ws = spreadsheet.add_worksheet(title=sheet_name, rows=max(1000, needed_rows), cols=25)
    print(f"📋 Created sheet '{sheet_name}'")
    sid = ws.id

    # --- Build data rows ---
    data_rows = []
    for chat in all_results:
        g = chat.get("grading", {}).get("criteria", {})
        url = f"https://app.crisp.chat/website/{chat['website_id']}/inbox/{chat['session_id']}"
        capped = [_score(g, k) for k in _KEY_MAP]
        total = round(sum(capped) / 2, 2)
        data_rows.append([
            chat["date"], url, chat["app"], chat["primary_operator"],
            total, *capped,
            chat.get("grading", {}).get("overall_summary", ""),
            "✅ Resolved" if chat.get("is_resolved") else "🔄 Open",
        ])

    # --- Agent summary ---
    agent_stats: dict[str, list[float]] = {}
    for chat in all_results:
        g = chat.get("grading", {}).get("criteria", {})
        capped = [_score(g, k) for k in _KEY_MAP]
        score = round(sum(capped) / 2, 2)
        agent_stats.setdefault(chat["primary_operator"], []).append(score)

    summary_rows = [["Support", "Avg Score (/10)", "Total Chats"]]
    for agent, scores in sorted(agent_stats.items()):
        summary_rows.append([agent, round(sum(scores) / len(scores), 2), len(scores)])

    total_data_rows = 1 + len(data_rows)   # header + data
    summary_start_row = total_data_rows + 2  # 1-indexed, leave 1 blank row gap

    # --- Write to sheet ---
    ws.update([_HEADERS], "A1", value_input_option="USER_ENTERED")
    if data_rows:
        ws.append_rows(data_rows, value_input_option="USER_ENTERED")
    ws.update(summary_rows, f"A{summary_start_row}", value_input_option="USER_ENTERED")

    # --- Formatting ---
    reqs = []
    note_reqs = []

    def repeat_cell(r0, r1, c0, c1, fmt, fields):
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                      "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": fmt},
            "fields": f"userEnteredFormat({fields})"
        }})

    def set_col_width(c0, c1, px):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"
        }})

    # Header — main table
    repeat_cell(0, 1, 0, len(_HEADERS), {
        "backgroundColor": _hex_to_color("1F4E78"),
        "textFormat": {"foregroundColor": _hex_to_color("FFFFFF"), "bold": True},
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"
    }, "backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy")

    # Header — summary table
    sum_r0 = summary_start_row - 1  # 0-indexed
    repeat_cell(sum_r0, sum_r0 + 1, 0, 3, {
        "backgroundColor": _hex_to_color("1F4E78"),
        "textFormat": {"foregroundColor": _hex_to_color("FFFFFF"), "bold": True},
        "horizontalAlignment": "CENTER"
    }, "backgroundColor,textFormat,horizontalAlignment")

    # Per data row: score color + deduction highlights + justification notes
    for row_offset, chat in enumerate(all_results):
        row_idx = 1 + row_offset  # 0-indexed (row 0 = header)
        g = chat.get("grading", {}).get("criteria", {})
        capped = [_score(g, k) for k in _KEY_MAP]
        score = round(sum(capped) / 2, 2)
        score_color = "FF6B6B" if score < 7 else "FFD966" if score < 9 else "6BCB77"
        repeat_cell(row_idx, row_idx + 1, 4, 5, {"backgroundColor": _hex_to_color(score_color)}, "backgroundColor")

        for col_offset, key in enumerate(_KEY_MAP):
            col_idx = 5 + col_offset
            val = g.get(key, {}).get("score", 0)
            if val < _MAX_SCORES[col_idx]:
                repeat_cell(row_idx, row_idx + 1, col_idx, col_idx + 1,
                             {"backgroundColor": _hex_to_color("FCE4D6")}, "backgroundColor")
            justification = g.get(key, {}).get("justification", "")
            if justification:
                note_reqs.append({"updateCells": {
                    "range": {"sheetId": sid, "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "rows": [{"values": [{"note": justification}]}],
                    "fields": "note"
                }})

    # Summary score colors
    for s_idx, (agent, scores) in enumerate(sorted(agent_stats.items()), 1):
        avg = sum(scores) / len(scores)
        color = "FF6B6B" if avg < 7 else "FFD966" if avg < 9 else "6BCB77"
        r = sum_r0 + s_idx
        repeat_cell(r, r + 1, 1, 2, {"backgroundColor": _hex_to_color(color)}, "backgroundColor")

    # Column widths + freeze header
    set_col_width(0, 1, 100)
    set_col_width(1, 2, 260)
    set_col_width(2, 3, 100)
    set_col_width(3, 4, 120)
    set_col_width(4, 5, 80)
    set_col_width(5, 19, 70)
    set_col_width(19, 20, 360)
    set_col_width(20, 21, 110)
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"
    }})

    spreadsheet.batch_update({"requests": reqs + note_reqs})
    sheet_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit#gid={sid}"
    print(f"✅ Exported to '{sheet_name}': {sheet_url}")


# ---------------------------------------------------------------------------
# MongoDB save
# ---------------------------------------------------------------------------

def _save_to_mongo(results: list[dict]) -> dict[str, int]:
    # Chỉ lưu (session_id, date) chưa có trong DB — cùng session ngày khác vẫn lưu được
    existing_keys = _already_saved_keys()
    new_results = [c for c in results if (c["session_id"], c["date"]) not in existing_keys]
    skipped = len(results) - len(new_results)
    if skipped:
        print(f"   ⏭  Bỏ qua {skipped} chat đã có trong DB")
    if not new_results:
        return {"inserted": 0, "replaced": 0}

    print(f"   Generating summaries + tags for {len(new_results)} chats...")
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
    summaries: dict[str, tuple[str | None, list[str]]] = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_generate_summary_and_tags, chat["transcript"]): chat["session_id"]
                for chat in new_results}
        for fut in _as_completed(futs):
            summaries[futs[fut]] = fut.result()

    records = []
    for chat in new_results:
        summary_text, tags = summaries.get(chat["session_id"], (None, []))
        records.append({
            "session_id":       chat["session_id"],
            "website_id":       chat["website_id"],
            "date":             chat["date"],
            "app":              chat["app"],
            "customer":         chat["customer"],
            "primary_operator": chat["primary_operator"],
            "is_resolved":      chat["is_resolved"],
            "transcript":       chat["transcript"],
            "summary":          summary_text,
            "tags":             tags or None,
            "grading":          chat["grading"],
            "crisp_url":        f"https://app.crisp.chat/website/{chat['website_id']}/inbox/{chat['session_id']}",
        })

    stats = upsert_many(records)

    # Also upsert into sumtag — append as new segment for this session
    sumtag_created = sumtag_appended = 0
    for chat in new_results:
        summary_text, tags = summaries.get(chat["session_id"], (None, []))
        if not summary_text:
            continue
        seg_data = {
            "start":   chat["date"] + " 00:00:00",
            "end":     chat["date"] + " 23:59:59",
            "tags":    tags,
            "summary": summary_text,
        }
        try:
            result = sumtag_append_segment(
                session_id=chat["session_id"],
                segment_data=seg_data,
                crawl_date=chat["date"],
                website_id=chat.get("website_id"),
                app=chat.get("app"),
            )
            if result == "created":    sumtag_created += 1
            elif result == "appended": sumtag_appended += 1
        except Exception as e:
            print(f"   ⚠️  sumtag append failed for {chat['session_id']}: {e}")

    if sumtag_created or sumtag_appended:
        print(f"   ✅ MongoDB sumtag: {sumtag_created} created, {sumtag_appended} appended")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_few_shot_examples()
    run_start = time.time()
    sheet_name = datetime.now().strftime("%H:%M")  # one sheet per run, named by timestamp

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date (YYYY-MM-DD), default today")
    parser.add_argument("--from", dest="date_from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to",   dest="date_to",   help="End date (YYYY-MM-DD)")
    parser.add_argument("--regrade", help="Path to existing JSON to re-grade")
    parser.add_argument("--no-mongo", action="store_true", help="Skip MongoDB save")
    args = parser.parse_args()

    all_results: list[dict] = []

    if args.regrade:
        if not os.path.exists(args.regrade):
            print(f"❌ File {args.regrade} not found.")
            return
        print(f"⚖️  Re-grading from {args.regrade}...")
        with open(args.regrade, "r", encoding="utf-8") as f:
            chats = json.load(f)
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        sheet_name += " (regraded)"
        all_results = _grade_date(chats, date_str, suffix="_regraded")

    elif args.date_from and args.date_to:
        d_from = datetime.strptime(args.date_from, "%Y-%m-%d")
        d_to   = datetime.strptime(args.date_to,   "%Y-%m-%d")
        if d_from > d_to:
            print("❌ --from phải trước --to.")
            return
        total_days = (d_to - d_from).days + 1
        print(f"📅 Date range: {args.date_from} → {args.date_to} ({total_days} ngày)")
        current = d_from
        while current <= d_to:
            date_str = current.strftime("%Y-%m-%d")
            print(f"\n{'='*50}\n📆 {date_str}\n{'='*50}")
            chats = fetch_chats(date_str)
            all_results += _grade_date(chats, date_str)
            current += timedelta(days=1)

    else:
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        chats = fetch_chats(date_str)
        all_results = _grade_date(chats, date_str)

    if not all_results:
        print("No results to export.")
        print(f"\n⏱  Total: {_fmt_elapsed(time.time() - run_start)}")
        return

    # Export all results to one sheet
    _export_to_gsheet(all_results, sheet_name)

    # Save to MongoDB
    if not args.no_mongo:
        print(f"🍃 Saving {len(all_results)} chats to MongoDB...")
        try:
            ensure_tunnel()
            stats = _save_to_mongo(all_results)
            print(f"   ✅ MongoDB: {stats['inserted']} inserted, {stats['replaced']} replaced")
        except Exception as e:
            print(f"   ⚠️  MongoDB save failed (non-fatal): {e}")
    else:
        print("ℹ️  --no-mongo: skipping MongoDB save")

    print(f"\n⏱  Total: {_fmt_elapsed(time.time() - run_start)}")


if __name__ == "__main__":
    main()
