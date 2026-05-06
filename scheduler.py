"""
scheduler.py — Tự động chấm điểm mỗi ngày lúc 9:00 sáng.

Chấm ngày hôm trước, lưu vào:
  - JSON local  (qa_report_YYYYMMDD.json)
  - Google Sheet "Support Analyzer" (append + tính lại summary agent)
  - MongoDB     (deco_chat collection)

Chạy:
  cd support_analyzer
  source venv/bin/activate
  python scheduler.py            # chạy vô thời hạn, tự chấm lúc 9:00 mỗi ngày
  python scheduler.py --now      # chấm ngay lập tức (test)
  python scheduler.py --date 2026-04-20   # chấm ngày cụ thể rồi thoát
"""

import os
import json
import time
import logging
import argparse
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed


import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

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

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scheduler.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHEET_NAME = "Support Analyzer"

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


def _hex(h):
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _score(criteria, key):
    return min(float(criteria.get(key, {}).get("score", 0)), _CAPS.get(key, 9999))


# ---------------------------------------------------------------------------
# Grade
# ---------------------------------------------------------------------------

def _grade_date(chats: list[dict], date_str: str) -> list[dict]:
    if not chats:
        log.info(f"  Không có chat nào ngày {date_str}.")
        return []

    log.info(f"⚖️  Grading {len(chats)} chats cho {date_str}...")
    args_list = [(i, len(chats), chat) for i, chat in enumerate(chats, 1)]
    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        for fut in as_completed({ex.submit(_grade_one, a): a for a in args_list}):
            r = fut.result()
            if r:
                results.append(r)

    if results:
        path = f"qa_report_{date_str.replace('-', '')}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        log.info(f"💾 JSON: {path}")

    return results


# ---------------------------------------------------------------------------
# Google Sheets — fixed sheet "Support Analyzer", append + recalc summary
# ---------------------------------------------------------------------------

def _get_or_create_sheet(spreadsheet, name: str):
    try:
        return spreadsheet.worksheet(name), True
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=2000, cols=25)
        return ws, False


def _export_to_support_analyzer(new_results: list[dict]):
    if not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        log.warning("Thiếu Google Sheets config.")
        return

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)

    # Retry khi Google API trả 503/500
    spreadsheet = None
    for attempt in range(5):
        try:
            spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
            break
        except Exception as e:
            wait = 10 * (2 ** attempt)
            log.warning(f"  Google Sheets lỗi (attempt {attempt+1}/5): {e} — thử lại sau {wait}s")
            time.sleep(wait)
    if spreadsheet is None:
        log.error("  ❌ Không kết nối được Google Sheets sau 5 lần thử.")
        return
    ws, existed = _get_or_create_sheet(spreadsheet, SHEET_NAME)
    sid = ws.id

    # --- Đọc data hiện có ---
    existing_urls: set[str] = set()
    existing_data_count = 0
    if existed:
        for row in ws.get_all_values()[1:]:
            if row and len(row) > 1 and row[1].startswith("https://app.crisp.chat"):
                existing_urls.add(row[1])
                existing_data_count += 1

    # --- Lọc chỉ lấy row mới ---
    to_add = [
        r for r in new_results
        if f"https://app.crisp.chat/website/{r['website_id']}/inbox/{r['session_id']}" not in existing_urls
    ]
    skipped = len(new_results) - len(to_add)
    if skipped:
        log.info(f"  ⏭  Sheet: bỏ qua {skipped} row đã có")
    if not to_add:
        log.info("  Sheet: không có row mới.")
    else:
        # Xóa summary cũ trước khi append — nếu không, append_rows sẽ nối SAU summary
        # thay vì sau dòng data cuối cùng
        if existed and existing_data_count > 0:
            old_summary_row = existing_data_count + 3  # header(1) + data(N) + blank(1) + summary
            ws.batch_clear([f"A{old_summary_row}:C{old_summary_row + 30}"])

        new_rows = []
        for chat in to_add:
            g = chat.get("grading", {}).get("criteria", {})
            url = f"https://app.crisp.chat/website/{chat['website_id']}/inbox/{chat['session_id']}"
            capped = [_score(g, k) for k in _KEY_MAP]
            total = round(sum(capped) / 2, 2)
            new_rows.append([
                chat["date"], url, chat["app"], chat["primary_operator"],
                total, *capped,
                chat.get("grading", {}).get("overall_summary", ""),
                "✅ Resolved" if chat.get("is_resolved") else "🔄 Open",
            ])
        ws.update([_HEADERS], "A1", value_input_option="USER_ENTERED")
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        log.info(f"  📊 Sheet: thêm {len(new_rows)} row mới")

    # --- Tính lại summary từ TOÀN BỘ data trong sheet ---
    all_rows = ws.get_all_values()
    agent_stats: dict[str, list[float]] = {}
    for row in all_rows[1:]:
        if len(row) < 5 or not row[1].startswith("https://app.crisp.chat"):
            continue
        try:
            agent_stats.setdefault(row[3], []).append(float(row[4]))
        except ValueError:
            continue

    summary_rows = [["Support", "Avg Score (/10)", "Total Chats"]]
    for agent, scores in sorted(agent_stats.items()):
        summary_rows.append([agent, round(sum(scores) / len(scores), 2), len(scores)])

    # Tính vị trí từ count đã biết — không phụ thuộc vào get_all_values() sau append
    last_data_row_1idx = 1 + existing_data_count + len(to_add)
    summary_start = last_data_row_1idx + 2  # 1-indexed, để 1 dòng trống

    # Xóa toàn bộ vùng sau data (bao gồm summary cũ có thể nằm sai vị trí)
    ws.batch_clear([f"A{last_data_row_1idx + 2}:C{last_data_row_1idx + 50}"])
    ws.update(summary_rows, f"A{summary_start}", value_input_option="USER_ENTERED")

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

    # Header chính
    repeat_cell(0, 1, 0, len(_HEADERS), {
        "backgroundColor": _hex("1F4E78"),
        "textFormat": {"foregroundColor": _hex("FFFFFF"), "bold": True},
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"
    }, "backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy")

    # Header summary
    sum_r0 = summary_start - 1
    repeat_cell(sum_r0, sum_r0 + 1, 0, 3, {
        "backgroundColor": _hex("1F4E78"),
        "textFormat": {"foregroundColor": _hex("FFFFFF"), "bold": True},
        "horizontalAlignment": "CENTER"
    }, "backgroundColor,textFormat,horizontalAlignment")

    # Reset background về trắng cho toàn bộ vùng new data rows
    # (tránh kế thừa formatting tối của summary cũ vẫn còn trên các cell đó)
    new_start_0idx = 1 + existing_data_count
    if to_add:
        reqs.insert(0, {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": new_start_0idx,
                      "endRowIndex": new_start_0idx + len(to_add),
                      "startColumnIndex": 0, "endColumnIndex": len(_HEADERS)},
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1}}},
            "fields": "userEnteredFormat(backgroundColor)"
        }})

    # Màu score + highlight trừ điểm + notes cho rows mới
    for offset, chat in enumerate(to_add):
        row_idx = new_start_0idx + offset
        g = chat.get("grading", {}).get("criteria", {})
        capped = [_score(g, k) for k in _KEY_MAP]
        score = round(sum(capped) / 2, 2)
        color = "FF6B6B" if score < 7 else "FFD966" if score < 9 else "6BCB77"
        repeat_cell(row_idx, row_idx + 1, 4, 5, {"backgroundColor": _hex(color)}, "backgroundColor")
        for col_offset, key in enumerate(_KEY_MAP):
            col_idx = 5 + col_offset
            if g.get(key, {}).get("score", 0) < _MAX_SCORES[col_idx]:
                repeat_cell(row_idx, row_idx + 1, col_idx, col_idx + 1,
                             {"backgroundColor": _hex("FCE4D6")}, "backgroundColor")
            justification = g.get(key, {}).get("justification", "")
            if justification:
                note_reqs.append({"updateCells": {
                    "range": {"sheetId": sid, "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "rows": [{"values": [{"note": justification}]}],
                    "fields": "note"
                }})

    # Màu avg score trong summary
    for s_idx, (agent, scores) in enumerate(sorted(agent_stats.items()), 1):
        avg = sum(scores) / len(scores)
        color = "FF6B6B" if avg < 7 else "FFD966" if avg < 9 else "6BCB77"
        r = sum_r0 + s_idx
        repeat_cell(r, r + 1, 1, 2, {"backgroundColor": _hex(color)}, "backgroundColor")

    set_col_width(0, 1, 100); set_col_width(1, 2, 260); set_col_width(2, 3, 100)
    set_col_width(3, 4, 120); set_col_width(4, 5, 80);  set_col_width(5, 19, 70)
    set_col_width(19, 20, 360); set_col_width(20, 21, 110)
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"
    }})

    spreadsheet.batch_update({"requests": reqs + note_reqs})
    url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit#gid={sid}"
    log.info(f"✅ Sheet '{SHEET_NAME}': {url}")


# ---------------------------------------------------------------------------
# MongoDB save
# ---------------------------------------------------------------------------

_SUMMARY_PROMPT = (
    "Bạn là trợ lý AI chuyên tóm tắt các cuộc hội thoại hỗ trợ khách hàng. "
    "Phân tích cuộc hội thoại và tạo bản tóm tắt rõ ràng, súc tích bằng tiếng Việt, bao gồm: "
    "Vấn đề hoặc câu hỏi chính của khách hàng; "
    "Hành động và giải pháp mà agent đã thực hiện; "
    "Thái độ nổi bật của khách hàng. "
    "Trình bày dạng bullet point, ngôn ngữ chuyên nghiệp."
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
            json={"model": MODEL, "max_tokens": 1024,
                  "messages": [{"role": "system", "content": _SUMMARY_PROMPT},
                                {"role": "user",   "content": transcript}]},
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
    except Exception:
        return None, []


def _save_to_mongo(results: list[dict]):
    # Chỉ lưu (session_id, date) chưa có trong DB — cùng session ngày khác vẫn lưu được
    try:
        col = get_db()["deco_chat"]
        session_ids = [c["session_id"] for c in results]
        saved_keys = {
            (d["session_id"], d["date"])
            for d in col.find({"session_id": {"$in": session_ids}}, {"session_id": 1, "date": 1})
        }
        to_save = [c for c in results if (c["session_id"], c["date"]) not in saved_keys]
        skipped = len(results) - len(to_save)
        if skipped:
            log.info(f"   ⏭  Bỏ qua {skipped} chat đã chấm trong ngày này")
        if not to_save:
            return
    except Exception as e:
        log.warning(f"   Không check được DB: {e}")
        to_save = results

    log.info(f"   Generating summaries + tags for {len(to_save)} chats...")
    summaries: dict[str, tuple[str | None, list[str]]] = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_generate_summary_and_tags, c["transcript"]): c["session_id"] for c in to_save}
        for fut in as_completed(futs):
            summaries[futs[fut]] = fut.result()

    records = []
    for c in to_save:
        summary_text, tags = summaries.get(c["session_id"], (None, []))
        records.append({
            "session_id":       c["session_id"],
            "website_id":       c["website_id"],
            "date":             c["date"],
            "app":              c["app"],
            "customer":         c["customer"],
            "primary_operator": c["primary_operator"],
            "is_resolved":      c["is_resolved"],
            "transcript":       c["transcript"],
            "summary":          summary_text,
            "tags":             tags or None,
            "grading":          c["grading"],
            "crisp_url":        f"https://app.crisp.chat/website/{c['website_id']}/inbox/{c['session_id']}",
        })

    stats = upsert_many(records)
    log.info(f"   ✅ MongoDB deco_chat: {stats['inserted']} inserted, {stats['replaced']} replaced")

    # Also upsert into sumtag — append as new segment for this session
    sumtag_created = sumtag_appended = 0
    for c in to_save:
        summary_text, tags = summaries.get(c["session_id"], (None, []))
        if not summary_text:
            continue
        seg_data = {
            "start":   c["date"] + " 00:00:00",
            "end":     c["date"] + " 23:59:59",
            "tags":    tags,
            "summary": summary_text,
        }
        try:
            result = sumtag_append_segment(
                session_id=c["session_id"],
                segment_data=seg_data,
                crawl_date=c["date"],
                website_id=c.get("website_id"),
                app=c.get("app"),
            )
            if result == "created":    sumtag_created += 1
            elif result == "appended": sumtag_appended += 1
        except Exception as e:
            log.warning(f"   sumtag append failed for {c['session_id']}: {e}")

    if sumtag_created or sumtag_appended:
        log.info(f"   ✅ MongoDB sumtag: {sumtag_created} created, {sumtag_appended} appended")


# ---------------------------------------------------------------------------
# Daily job
# ---------------------------------------------------------------------------

def run_daily_job(date_str: str | None = None):
    if date_str is None:
        yesterday = datetime.now(timezone(timedelta(hours=7))) - timedelta(days=1)
        date_str = yesterday.strftime("%Y-%m-%d")

    log.info(f"\n{'='*55}")
    log.info(f"🚀 Daily job — chấm ngày {date_str}")
    log.info(f"{'='*55}")
    t0 = time.time()

    try:
        chats = fetch_chats(date_str)
        results = _grade_date(chats, date_str)

        if results:
            _export_to_support_analyzer(results)
            _save_to_mongo(results)

        log.info(f"✅ Xong — {_fmt_elapsed(time.time() - t0)}")
    except Exception as e:
        log.error(f"❌ Job thất bại: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_TZ7 = timezone(timedelta(hours=7))


def _seconds_until_9am_vn() -> float:
    """Tính số giây đến 09:00 sáng giờ Việt Nam (UTC+7) tiếp theo."""
    now = datetime.now(_TZ7)
    target = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--now",  action="store_true", help="Chấm ngay (hôm qua)")
    parser.add_argument("--date", help="Chấm ngày cụ thể YYYY-MM-DD rồi thoát")
    args = parser.parse_args()

    load_few_shot_examples()
    ensure_tunnel()

    if args.date:
        run_daily_job(args.date)
    elif args.now:
        run_daily_job()
    else:
        # Nếu khởi động sau 9h VN và chưa chấm hôm nay → chấm bổ sung ngay
        now_vn = datetime.now(_TZ7)
        if now_vn.hour >= 9:
            yesterday = (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")
            log.info(f"  Đã qua 09:00 VN — chấm bổ sung ngày {yesterday}")
            run_daily_job(yesterday)

        while True:
            wait = _seconds_until_9am_vn()
            next_run = datetime.now(_TZ7) + timedelta(seconds=wait)
            log.info(f"⏰ Chờ đến 09:00 VN — còn {wait/3600:.1f}h ({next_run.strftime('%Y-%m-%d %H:%M VN')})")
            time.sleep(wait)
            run_daily_job()
