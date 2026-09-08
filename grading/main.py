import os
import sys
import json
import argparse
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from dotenv import load_dotenv

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `database` package

from analyzer_v2 import (
    fetch_chats,
    fetch_pending_chats,
    load_few_shot_examples,
    _grade_one,
    _fmt_elapsed,
    OPENROUTER_API_KEY,
    MODEL,
)

from database.tunnel import ensure_tunnel
from database.deco_chat import upsert_many, get_all_saved_keys
from database.sumtag import upsert as sumtag_upsert

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
# Grade one date, return results (also saves local JSON)
# ---------------------------------------------------------------------------

def _already_saved_keys() -> set[tuple[str, str]]:
    """Lấy tất cả (session_id, date) đã có trong tất cả grading collections."""
    try:
        ensure_tunnel()
        return get_all_saved_keys()
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
            "shop_domain":      chat.get("shop_domain"),
        })

    stats = upsert_many(records)

    # Also upsert into sumtag — one record per (session_id, date)
    sumtag_inserted = sumtag_replaced = 0
    for chat in new_results:
        summary_text, tags = summaries.get(chat["session_id"], (None, []))
        if not summary_text:
            continue
        try:
            result = sumtag_upsert(
                session_id=chat["session_id"],
                date=chat["date"],
                tags=tags,
                summary=summary_text,
                website_id=chat.get("website_id"),
                app=chat.get("app"),
                primary_operator=chat.get("primary_operator"),
                start=chat.get("seg_start"),
                end=chat.get("seg_end"),
                msg_count=chat.get("seg_msg_count"),
                shop_domain=chat.get("shop_domain"),
            )
            if result == "inserted":  sumtag_inserted += 1
            else:                     sumtag_replaced += 1
        except Exception as e:
            print(f"   ⚠️  sumtag upsert failed for {chat['session_id']}: {e}")

    if sumtag_inserted or sumtag_replaced:
        print(f"   ✅ MongoDB sumtag: {sumtag_inserted} inserted, {sumtag_replaced} replaced")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_few_shot_examples()
    run_start = time.time()

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date (YYYY-MM-DD), default today")
    parser.add_argument("--from", dest="date_from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to",   dest="date_to",   help="End date (YYYY-MM-DD)")
    parser.add_argument("--regrade", help="Path to existing JSON to re-grade")
    parser.add_argument("--no-mongo", action="store_true", help="Skip MongoDB save")
    args = parser.parse_args()

    all_results: list[dict] = []

    # Tunnel + pending callback (skip for --no-mongo and --regrade)
    _tunnel_ready = False
    def _ensure_tunnel_once():
        nonlocal _tunnel_ready
        if not _tunnel_ready:
            ensure_tunnel()
            _tunnel_ready = True

    def _handle_pending(session_id, website_id, app, original_date):
        """Callback: save session to pending_chats when LLM marks it incomplete."""
        try:
            _ensure_tunnel_once()
            from database.pending import add as pending_add
            pending_add(session_id, website_id, app, original_date)
        except Exception as e:
            print(f"  ⚠️  Could not save pending {session_id}: {e}")

    on_pending = _handle_pending if not args.no_mongo else None

    if args.regrade:
        if not os.path.exists(args.regrade):
            print(f"❌ File {args.regrade} not found.")
            return
        print(f"⚖️  Re-grading from {args.regrade}...")
        with open(args.regrade, "r", encoding="utf-8") as f:
            chats = json.load(f)
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
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
            chats = fetch_chats(date_str, on_pending=on_pending)
            all_results += _grade_date(chats, date_str)
            current += timedelta(days=1)

    else:
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        # Retry pending sessions from previous days first
        if not args.no_mongo:
            try:
                _ensure_tunnel_once()
                pending_chats = fetch_pending_chats()
                if pending_chats:
                    all_results += _grade_date(pending_chats, date_str)
            except Exception as e:
                print(f"  ⚠️  Pending retry failed (non-fatal): {e}")
        chats = fetch_chats(date_str, on_pending=on_pending)
        all_results += _grade_date(chats, date_str)

    if not all_results:
        print("No results to export.")
        print(f"\n⏱  Total: {_fmt_elapsed(time.time() - run_start)}")
        return

    # Save to MongoDB
    if not args.no_mongo:
        print(f"🍃 Saving {len(all_results)} chats to MongoDB...")
        try:
            _ensure_tunnel_once()
            stats = _save_to_mongo(all_results)
            print(f"   ✅ MongoDB: {stats['inserted']} inserted, {stats['replaced']} replaced")
        except Exception as e:
            print(f"   ⚠️  MongoDB save failed (non-fatal): {e}")
    else:
        print("ℹ️  --no-mongo: skipping MongoDB save")

    print(f"\n⏱  Total: {_fmt_elapsed(time.time() - run_start)}")


if __name__ == "__main__":
    main()
