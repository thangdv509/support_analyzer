"""
import_sumtag.py — Import crawl summary JSON → sumtag collection, then catch-up crawl.

Steps:
  1. Load data/crawl_20250101_20260325_summary.json → bulk insert into sumtag
  2. Crawl from 2026-03-26 to today (with do_summary=True) → append new segments

Chạy:
    python import_sumtag.py                     # full import + catch-up
    python import_sumtag.py --no-import         # chỉ catch-up crawl
    python import_sumtag.py --from 2026-04-01   # catch-up từ ngày cụ thể
"""

import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from database.tunnel import ensure_tunnel
from database.sumtag import upsert_session, append_segment, get_session
from crawl import fetch_websites, fetch_operators, crawl_date, _summarize_segment

load_dotenv()

TZ7 = timezone(timedelta(hours=7))
JSON_PATH = Path(__file__).resolve().parent / "data" / "crawl_20250101_20260325_summary.json"


def import_json():
    print(f"📂 Loading {JSON_PATH.name}...")
    with open(JSON_PATH, encoding="utf-8") as f:
        records = json.load(f)
    print(f"  → {len(records)} records")

    inserted = replaced = 0
    for rec in records:
        # Strip raw messages from segments — keep summary/tags/metadata only
        clean_segments = []
        for seg in rec.get("segments", []):
            clean_seg = {k: v for k, v in seg.items() if k != "messages"}
            clean_segments.append(clean_seg)

        doc = {
            "session_id":    rec["session_id"],
            "website_id":    rec.get("website_id", "unknown"),
            "state":         rec.get("state"),
            "crawl_date":    rec.get("crawl_date", "2026-03-25"),
            "start_session": rec.get("start_session"),
            "end_session":   rec.get("end_session"),
            "msg_count":     rec.get("msg_count", 0),
            "segment_count": len(clean_segments),
            "segments":      clean_segments,
        }
        result = upsert_session(doc)
        if result == "inserted":
            inserted += 1
        else:
            replaced += 1

    print(f"  ✅ JSON import done: {inserted} inserted, {replaced} replaced")


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

    total_created = total_appended = total_skipped = 0

    for website in websites:
        website_id = str(website["website_id"])
        print(f"\n🌐 Website: {website_id}")
        operators_raw = fetch_operators(website_id)

        for date_str in dates:
            # Fetch conversations WITHOUT summary — raw messages are still in each segment
            day_results = crawl_date(website_id, date_str, operators_raw, do_summary=False)
            if not day_results:
                continue

            created = appended = skipped = 0
            for conv in day_results:
                session_id = conv["session_id"]

                # Find which segment starts are already in sumtag for this session
                existing_doc = get_session(session_id)
                known_starts: set[str] = set()
                if existing_doc:
                    known_starts = {s.get("start") for s in existing_doc.get("segments", []) if s.get("start")}

                for seg in conv.get("segments", []):
                    seg_start = seg.get("start")
                    if seg_start and seg_start in known_starts:
                        skipped += 1
                        continue

                    # Only call LLM for segments we haven't summarized yet
                    result = _summarize_segment(seg.get("messages", []))
                    if not result:
                        continue

                    seg_data = {
                        "msg_count": seg.get("msg_count"),
                        "start":     seg_start,
                        "end":       seg.get("end"),
                        "tags":      result["tags"],
                        "summary":   result["summary"],
                    }
                    outcome = append_segment(
                        session_id=session_id,
                        segment_data=seg_data,
                        crawl_date=date_str,
                        website_id=conv.get("website_id"),
                        state=conv.get("state"),
                        start_session=conv.get("start_session"),
                        end_session=conv.get("end_session"),
                        msg_count=conv.get("msg_count"),
                    )
                    if outcome == "created":    created += 1
                    elif outcome == "appended": appended += 1
                    elif outcome == "skipped":  skipped += 1

            total_created  += created
            total_appended += appended
            total_skipped  += skipped
            print(f"  {date_str}: {created} created, {appended} appended, {skipped} skipped")

    print(f"\n✅ Catch-up done: {total_created} created, {total_appended} appended, {total_skipped} skipped")


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
