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
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed


import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `database` package

from analyzer_v2 import (
    fetch_chats,
    load_few_shot_examples,
    _grade_one,
    _fmt_elapsed,
    OPENROUTER_API_KEY,
    MODEL,
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