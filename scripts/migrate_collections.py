"""
migrate_collections.py — Chuyển dữ liệu cũ sang collections mới theo app.

1. deco_chat → grading_deco / grading_searchpie  (bỏ Unknown)
2. sumtag (nested segments) → sumtag_deco / sumtag_searchpie (flat, mỗi segment = 1 record)

Chạy:
    python migrate_collections.py
    python migrate_collections.py --dry-run   # chỉ in thống kê, không ghi
"""

import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `database` package

from database.tunnel import ensure_tunnel
from database.connection import get_db
from database.deco_chat import upsert_many as grading_upsert_many, _collection_name as grading_col_name
from database.sumtag import upsert_many as sumtag_upsert_many, _collection_name as sumtag_col_name, record_uuid

load_dotenv()


def _detect_app_from_text(text: str) -> str | None:
    u = text.upper()
    if "DECO" in u:
        return "DECO"
    if "SEARCHPIE" in u or "SEARCH PIE" in u:
        return "SearchPie"
    return None


def _infer_app(doc: dict) -> str | None:
    """Infer app from doc fields: app field first, then scan summaries/tags."""
    app = doc.get("app")
    if app and _detect_app_from_text(app):
        return _detect_app_from_text(app)
    for seg in doc.get("segments", []):
        result = _detect_app_from_text(seg.get("summary", ""))
        if result:
            return result
        for tag in seg.get("tags", []):
            result = _detect_app_from_text(tag)
            if result:
                return result
    return None


def migrate_grading(db, dry_run: bool):
    print("\n━━━ Migrate deco_chat → grading_deco / grading_searchpie ━━━")
    old = db["deco_chat"]
    total = old.count_documents({})
    print(f"  Source: deco_chat ({total} documents)")

    records = []
    skipped = 0
    for doc in old.find({}):
        app = doc.get("app", "")
        if not grading_col_name(app):
            skipped += 1
            continue
        doc.pop("_id", None)
        records.append(doc)

    print(f"  To migrate: {len(records)} | Skipped (Unknown): {skipped}")
    if not dry_run and records:
        stats = grading_upsert_many(records)
        print(f"  ✅ inserted={stats['inserted']} replaced={stats['replaced']}")
    elif dry_run:
        from collections import Counter
        counts = Counter(grading_col_name(r.get("app")) for r in records)
        for col, n in counts.items():
            print(f"     → {col}: {n}")


def migrate_sumtag(db, dry_run: bool):
    print("\n━━━ Migrate sumtag (nested) → sumtag_deco / sumtag_searchpie (flat) ━━━")
    old = db["sumtag"]
    total = old.count_documents({})
    print(f"  Source: sumtag ({total} documents)")

    records = []
    skipped_doc = skipped_seg = 0

    for doc in old.find({}):
        app = _infer_app(doc)
        if not app or not sumtag_col_name(app):
            skipped_doc += 1
            continue

        session_id = doc["session_id"]
        website_id = doc.get("website_id", "unknown")

        segments = doc.get("segments", [])
        if not segments:
            skipped_doc += 1
            continue

        for seg in segments:
            summary = seg.get("summary", "")
            if not summary:
                skipped_seg += 1
                continue

            end_str   = seg.get("end", "")
            start_str = seg.get("start", "")
            date = (end_str or start_str or "")[:10]
            if not date:
                skipped_seg += 1
                continue

            records.append({
                "session_id":       session_id,
                "date":             date,
                "website_id":       website_id,
                "app":              app,
                "primary_operator": doc.get("primary_operator"),
                "start":            start_str or None,
                "end":              end_str or None,
                "msg_count":        seg.get("msg_count"),
                "tags":             seg.get("tags", []),
                "summary":          summary,
            })

    print(f"  Flat records: {len(records)} | Skipped docs: {skipped_doc} | Skipped segs: {skipped_seg}")
    if not dry_run and records:
        stats = sumtag_upsert_many(records)
        print(f"  ✅ inserted={stats['inserted']} replaced={stats['replaced']}")
    elif dry_run:
        from collections import Counter
        counts = Counter(sumtag_col_name(r.get("app")) for r in records)
        for col, n in counts.items():
            print(f"     → {col}: {n}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Chỉ thống kê, không ghi vào DB")
    args = parser.parse_args()

    if args.dry_run:
        print("🔍 DRY RUN — không ghi dữ liệu")

    print("🔌 Connecting to MongoDB...")
    ensure_tunnel()
    db = get_db()

    migrate_grading(db, args.dry_run)
    migrate_sumtag(db, args.dry_run)

    if not args.dry_run:
        print("\n✅ Migration hoàn tất.")
        print("   Có thể drop collections cũ sau khi xác nhận dữ liệu:")
        print("   db.deco_chat.drop()")
        print("   db.sumtag.drop()")


if __name__ == "__main__":
    main()
