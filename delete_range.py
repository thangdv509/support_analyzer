"""
delete_range.py — Xóa data trong khoảng ngày khỏi tất cả grading + sumtag collections.

Chạy:
    python delete_range.py --from 2026-05-10 --to 2026-05-18
    python delete_range.py --from 2026-05-10 --to 2026-05-18 --dry-run
"""

import argparse
from dotenv import load_dotenv
load_dotenv()

from database.tunnel import ensure_tunnel
from database.connection import get_db
from database.deco_chat import ALL_GRADING_COLLECTIONS
from database.sumtag import ALL_SUMTAG_COLLECTIONS

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to",   dest="date_to",   required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("🔌 Connecting...")
    ensure_tunnel()
    db = get_db()

    query = {"date": {"$gte": args.date_from, "$lte": args.date_to}}
    all_cols = ALL_GRADING_COLLECTIONS + ALL_SUMTAG_COLLECTIONS

    total = 0
    for col_name in all_cols:
        count = db[col_name].count_documents(query)
        print(f"  {col_name}: {count} documents")
        total += count

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Tổng: {total} documents sẽ bị xóa ({args.date_from} → {args.date_to})")

    if args.dry_run:
        print("Dry run — không xóa.")
        return

    if total == 0:
        print("Không có gì để xóa.")
        return

    confirm = input("\n⚠️  Xác nhận xóa? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Hủy.")
        return

    for col_name in all_cols:
        result = db[col_name].delete_many(query)
        print(f"  ✅ {col_name}: đã xóa {result.deleted_count}")

    print("✅ Xong.")

if __name__ == "__main__":
    main()
