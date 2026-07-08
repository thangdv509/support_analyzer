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
from database.deco_chat import upsert_many, get_all_saved_keys
from database.sumtag import upsert as sumtag_upsert

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


def _apply_conditional_formatting(spreadsheet, sid: int):
    """Xóa CF rules cũ của sheet rồi thêm lại rules cho cột E (Rating) và B (Avg Score).
    Tách thành batch riêng để tránh lỗi khi batch chính quá lớn.
    """
    def _cf(col_start, col_end, condition_type, values, hex_color):
        vals = [{"userEnteredValue": v} for v in (values if isinstance(values, list) else [values])]
        return {"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": 9999,
                            "startColumnIndex": col_start, "endColumnIndex": col_end}],
                "booleanRule": {
                    "condition": {"type": condition_type, "values": vals},
                    "format": {"backgroundColorStyle": {"rgbColor": _hex(hex_color)}},
                }
            },
            "index": 0,
        }}

    # Đọc số CF rules hiện có để xóa trước (tránh duplicate mỗi lần chạy)
    delete_reqs: list[dict] = []
    try:
        sh_meta = spreadsheet.fetch_sheet_metadata()
        for sh in sh_meta.get("sheets", []):
            if sh["properties"]["sheetId"] == sid:
                n = len(sh.get("conditionalFormats", []))
                for i in range(n - 1, -1, -1):  # xóa từ cuối lên để giữ đúng index
                    delete_reqs.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
                break
    except Exception as e:
        log.warning(f"  ⚠️  Không đọc được CF rules cũ: {e}")

    # 3 mức màu: đỏ < 7, vàng 7–8.9999, xanh ≥ 9
    # NUMBER_GREATER_EQ không hợp lệ trong CF → dùng NUMBER_GREATER với 8.9999
    # (điểm làm tròn 2 chữ số nên không có giá trị nào nằm giữa 8.9999 và 9.0)
    add_reqs = []
    for col_s, col_e in [(4, 5), (1, 2)]:  # E (Rating), B (Avg Score summary)
        add_reqs.append(_cf(col_s, col_e, "NUMBER_GREATER", "8.9999",           "6BCB77"))
        add_reqs.append(_cf(col_s, col_e, "NUMBER_BETWEEN", ["7", "8.9999"],    "FFD966"))
        add_reqs.append(_cf(col_s, col_e, "NUMBER_LESS",    "7",                "FF6B6B"))

    cf_reqs = delete_reqs + add_reqs
    try:
        spreadsheet.batch_update({"requests": cf_reqs})
        log.info(f"  🎨 CF rules: xóa {len(delete_reqs)}, thêm {len(add_reqs)}")
    except Exception as e:
        log.error(f"  ❌ CF batch_update lỗi: {e}")


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
    last_data_row_1idx = 1  # vị trí thực của dòng data cuối (1-indexed)
    if existed:
        for i, row in enumerate(ws.get_all_values()[1:], 2):  # i = row số 1-indexed
            if row and len(row) > 1 and row[1].startswith("https://app.crisp.chat"):
                existing_urls.add(row[1])
                existing_data_count += 1
                last_data_row_1idx = i  # track vị trí thực, không chỉ đếm

    # --- Lọc chỉ lấy row mới và có grading hợp lệ ---
    to_add = [
        r for r in new_results
        if f"https://app.crisp.chat/website/{r['website_id']}/inbox/{r['session_id']}" not in existing_urls
        and r.get("grading", {}).get("criteria")  # bỏ qua record thiếu grading
    ]
    no_grading = sum(1 for r in new_results if not r.get("grading", {}).get("criteria"))
    skipped = len(new_results) - len(to_add) - no_grading
    if no_grading:
        log.info(f"  ⚠️  Bỏ qua {no_grading} record thiếu grading")
    if skipped:
        log.info(f"  ⏭  Sheet: bỏ qua {skipped} row đã có")
    if not to_add:
        log.info("  Sheet: không có row mới.")

    # Luôn đảm bảo header đúng
    ws.update([_HEADERS], "A1", value_input_option="USER_ENTERED")

    # Xóa toàn bộ vùng sau dòng data cuối cùng (tính theo vị trí thực, không phải đếm).
    # Range rộng 2000 rows để bắt mọi summary lạc chỗ từ các lần chạy trước bị lỗi.
    first_free_1idx = last_data_row_1idx + 1
    ws.batch_clear([f"A{first_free_1idx}:Z{first_free_1idx + 2000}"])

    if to_add:
        new_rows = []
        for i, chat in enumerate(to_add):
            row_1idx = first_free_1idx + i
            g = chat.get("grading", {}).get("criteria", {})
            url = f"https://app.crisp.chat/website/{chat['website_id']}/inbox/{chat['session_id']}"
            capped = [_score(g, k) for k in _KEY_MAP]
            new_rows.append([
                chat["date"], url, chat["app"], chat["primary_operator"],
                f"=ROUND(SUM(F{row_1idx}:S{row_1idx})/2,2)",  # formula, tự cập nhật khi sửa điểm
                *capped,
                chat.get("grading", {}).get("overall_summary", ""),
                "✅ Resolved" if chat.get("is_resolved") else "🔄 Open",
            ])
        ws.update(new_rows, f"A{first_free_1idx}", value_input_option="USER_ENTERED")
        log.info(f"  📊 Sheet: thêm {len(new_rows)} row mới")

    # --- Summary: dùng AVERAGEIF/COUNTIF để tự cập nhật khi sửa điểm trực tiếp trên sheet ---
    all_rows = ws.get_all_values()
    agent_stats: dict[str, list[float]] = {}
    for row in all_rows[1:]:
        if len(row) < 5 or not row[1].startswith("https://app.crisp.chat"):
            continue
        try:
            agent_stats.setdefault(row[3], []).append(float(row[4]))
        except ValueError:
            continue

    final_last_data_row_1idx = last_data_row_1idx + len(to_add)
    summary_start = final_last_data_row_1idx + 2  # để 1 dòng trống

    summary_rows = [["Support", "Avg Score (/10)", "Total Chats"]]
    for i, agent in enumerate(sorted(agent_stats.keys())):
        r = summary_start + 1 + i  # 1-indexed row của dòng agent này
        summary_rows.append([
            agent,
            f'=IFERROR(ROUND(AVERAGEIF($D$2:$D$9999,A{r},$E$2:$E$9999),2),"")',
            f'=IFERROR(COUNTIF($D$2:$D$9999,A{r}),"")',
        ])
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
    new_start_0idx = last_data_row_1idx  # 0-indexed: dòng đầu tiên của data mới
    if to_add:
        reqs.insert(0, {"repeatCell": {
            "range": {"sheetId": sid,
                      "startRowIndex": new_start_0idx,
                      "endRowIndex": new_start_0idx + len(to_add),
                      "startColumnIndex": 0, "endColumnIndex": len(_HEADERS)},
            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1}}},
            "fields": "userEnteredFormat(backgroundColor)"
        }})

    # Highlight trừ điểm + notes cho rows mới
    for offset, chat in enumerate(to_add):
        row_idx = new_start_0idx + offset
        g = chat.get("grading", {}).get("criteria", {})
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

    set_col_width(0, 1, 100); set_col_width(1, 2, 260); set_col_width(2, 3, 100)
    set_col_width(3, 4, 120); set_col_width(4, 5, 80);  set_col_width(5, 19, 70)
    set_col_width(19, 20, 360); set_col_width(20, 21, 110)
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"
    }})

    # Batch 1: formatting chính (headers, màu ô trừ điểm, col width, freeze)
    spreadsheet.batch_update({"requests": reqs + note_reqs})

    # Batch 2: Conditional formatting cho E (Rating) và B (Avg Score summary)
    # Tách riêng để tránh lỗi batch quá lớn khi reexport nhiều rows
    _apply_conditional_formatting(spreadsheet, sid)


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
        saved_keys = get_all_saved_keys()
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
    log.info(f"   ✅ MongoDB grading: {stats['inserted']} inserted, {stats['replaced']} replaced")

    # Also upsert into sumtag — one record per (session_id, date)
    sumtag_inserted = sumtag_replaced = 0
    for c in to_save:
        summary_text, tags = summaries.get(c["session_id"], (None, []))
        if not summary_text:
            continue
        try:
            result = sumtag_upsert(
                session_id=c["session_id"],
                date=c["date"],
                tags=tags,
                summary=summary_text,
                website_id=c.get("website_id"),
                app=c.get("app"),
                primary_operator=c.get("primary_operator"),
                start=c.get("seg_start"),
                end=c.get("seg_end"),
                msg_count=c.get("seg_msg_count"),
            )
            if result == "inserted":  sumtag_inserted += 1
            else:                     sumtag_replaced += 1
        except Exception as e:
            log.warning(f"   sumtag upsert failed for {c['session_id']}: {e}")

    if sumtag_inserted or sumtag_replaced:
        log.info(f"   ✅ MongoDB sumtag: {sumtag_inserted} inserted, {sumtag_replaced} replaced")


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

    ensure_tunnel()

    try:
        chats = fetch_chats(date_str)
        results = _grade_date(chats, date_str)

        if results:
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
    target = now.replace(hour=2, minute=0, second=0, microsecond=0)
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
        if now_vn.hour >= 2:
            yesterday = (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")
            log.info(f"  Đã qua 09:00 VN — chấm bổ sung ngày {yesterday}")
            run_daily_job(yesterday)

        while True:
            wait = _seconds_until_9am_vn()
            next_run = datetime.now(_TZ7) + timedelta(seconds=wait)
            log.info(f"⏰ Chờ đến 09:00 VN — còn {wait/3600:.1f}h ({next_run.strftime('%Y-%m-%d %H:%M VN')})")
            time.sleep(wait)
            run_daily_job()