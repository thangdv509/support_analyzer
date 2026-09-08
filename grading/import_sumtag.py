"""
import_sumtag.py — Import crawl summary JSON → sumtag collection, then catch-up crawl.

Mỗi segment trong JSON (hoặc từ crawl) → một flat record (session_id, date).
Date = ngày kết thúc segment (end[:10]), mirror logic analyzer_v2.

Steps:
  1. Load data/crawl_20250101_20260325_summary.json → bulk insert into sumtag
  2. Crawl từ 2026-03-26 đến hôm nay → thêm records mới

Chạy:
    python import_sumtag.py
    python import_sumtag.py --no-import         # chỉ catch-up crawl
    python import_sumtag.py --from 2026-04-01   # catch-up từ ngày cụ thể
"""

import sys
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `database` package

from database.tunnel import ensure_tunnel
from database.sumtag import upsert_many, exists
from crawl import fetch_websites, fetch_operators, crawl_date, _summarize_segment

load_dotenv()

TZ7 = timezone(timedelta(hours=7))
JSON_PATH = Path(__file__).resolve().parent / "data" / "crawl_20250101_20260325_summary.json"


def import_json():
    print(f"📂 Loading {JSON_PATH.name}...")
    with open(JSON_PATH, encoding="utf-8") as f:
        sessions = json.load(f)
    print(f"  → {len(sessions)} sessions")

    records = []
    skipped = 0
    for sess in sessions:
        session_id = sess["session_id"]
        website_id = sess.get("website_id", "unknown")

        for seg in sess.get("segments", []):
            if not seg.get("summary"):
                skipped += 1
                continue

            # Dùng end date làm date — ngày segment kết thúc (activity cuối)
            end_str   = seg.get("end", "")
            start_str = seg.get("start", "")
            date = (end_str or start_str)[:10]
            if not date:
                skipped += 1
                continue

            records.append({
                "session_id": session_id,
                "date":       date,
                "website_id": website_id,
                "app":        None,   # sẽ backfill bằng update_sumtag_app.py
                "start":      start_str or None,
                "end":        end_str or None,
                "msg_count":  seg.get("msg_count"),
                "tags":       seg.get("tags", []),
                "summary":    seg["summary"],
            })

    print(f"  → {len(records)} records (skipped {skipped} segments without summary)")
    stats = upsert_many(records)
    print(f"  ✅ Imported: {stats['inserted']} inserted, {stats['replaced']} replaced")


def catchup_crawl(from_date: str, to_date: str):
    print(f"\n🕐 Catch-up crawl: {from_date} → {to_date}")

    websites = fetch_websites()
    if not websites:
        print("❌ No websites found")
        return

    d_from = datetime.strptime(from_date, "%Y-%m-%d")
    d_to   = datetime.strptime(to_date,   "%Y-%m-%d")
    dates  = [(d_from + timedelta(days=i)).strftime("%Y-%m-%d")
              for i in range((d_to - d_from).days + 1)]

    total_inserted = total_skipped = 0

    for website in websites:
        website_id = str(website["website_id"])
        print(f"\n🌐 Website: {website_id}")
        operators_raw = fetch_operators(website_id)

        for date_str in dates:
            # Fetch conversations without summary — raw messages in each segment
            day_results = crawl_date(website_id, date_str, operators_raw, do_summary=False)
            if not day_results:
                continue

            inserted = skipped = 0
            for conv in day_results:
                session_id = conv["session_id"]

                # Find the segment that had activity on this date (mirror analyzer logic)
                # = last segment with any message timestamp in [date_str 00:00 → date_str 23:59]
                day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ7)
                day_end   = day_start + timedelta(days=1)

                valid_seg = None
                for seg in reversed(conv.get("segments", [])):
                    msgs = seg.get("messages", [])
                    if any(
                        day_start <= datetime.fromtimestamp(m.get("timestamp", 0) / 1000, tz=TZ7) < day_end
                        and m.get("type") not in ("event", "note")
                        for m in msgs if m.get("timestamp")
                    ):
                        valid_seg = seg
                        break

                if valid_seg is None:
                    skipped += 1
                    continue

                # Skip if already in sumtag
                if exists(session_id, date_str):
                    skipped += 1
                    continue

                # Summarize only this segment (LLM call)
                result = _summarize_segment(valid_seg.get("messages", []))
                if not result:
                    skipped += 1
                    continue

                # Real timestamps from messages
                chat_msgs = [m for m in valid_seg.get("messages", [])
                             if m.get("type") not in ("event", "note", "animation") and m.get("timestamp")]
                ts_list = [m["timestamp"] for m in chat_msgs]
                seg_start = datetime.fromtimestamp(min(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S") if ts_list else None
                seg_end   = datetime.fromtimestamp(max(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S") if ts_list else None

                from database.sumtag import upsert as sumtag_upsert
                sumtag_upsert(
                    session_id=session_id,
                    date=date_str,
                    tags=result["tags"],
                    summary=result["summary"],
                    website_id=conv.get("website_id"),
                    start=seg_start,
                    end=seg_end,
                    msg_count=len(chat_msgs),
                )
                inserted += 1

            total_inserted += inserted
            total_skipped  += skipped
            if inserted:
                print(f"  {date_str}: {inserted} inserted, {skipped} skipped")

    print(f"\n✅ Catch-up done: {total_inserted} inserted, {total_skipped} skipped")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-import", action="store_true",
                        help="Skip JSON import, only do catch-up crawl")
    parser.add_argument("--from", dest="from_date",
                        help="Catch-up start date YYYY-MM-DD (default: 2026-03-26)")
    parser.add_argument("--to", dest="to_date",
                        help="Catch-up end date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    print("🔌 Connecting to MongoDB...")
    ensure_tunnel()

    if not args.no_import:
        import_json()

    from_date = args.from_date or "2026-03-26"
    to_date   = args.to_date   or datetime.now(TZ7).strftime("%Y-%m-%d")
    catchup_crawl(from_date, to_date)


if __name__ == "__main__":
    main()
