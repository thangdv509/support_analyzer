"""Backfill crawl_stats cho khoảng ngày quá khứ — đếm lại số conversation THẬT trên Crisp
mỗi ngày (KHÔNG re-grade, không gọi LLM, chỉ đếm) để đối chiếu với số đã chấm hiện có trong
grading_deco/grading_searchpie.

QUAN TRỌNG về cách quét: Crisp trả conversation theo thứ tự updated_at MỚI NHẤT TRƯỚC, không
hỗ trợ nhảy thẳng tới 1 ngày cụ thể. Đếm riêng từng ngày (phân trang lại từ đầu mỗi lần) sẽ
cần hàng chục nghìn trang cho khoảng 4 tháng — không khả thi. Script này quét 1 LẦN DUY NHẤT
từ hôm nay lùi về date_from, gộp đếm theo ngày trong lúc quét (session_id dedup theo ngày).

Chạy:
    python backfill_crawl_stats.py --from 2026-04-01 --to 2026-07-23
"""
import os
import sys
import time
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from crisp_api import Crisp

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `database` package

from database.tunnel import ensure_tunnel
from database.connection import get_db
from database.crawl_stats import upsert_stats

IDENTIFIER = os.getenv("CRISP_IDENTIFIER")
KEY = os.getenv("CRISP_KEY")
TZ7 = timezone(timedelta(hours=7))
MAX_PAGES = 3000  # an toàn — chặn vòng lặp chạy vô hạn, thực tế sẽ dừng sớm hơn nhờ cutoff date


def _sweep(client: Crisp, website_id: str, cutoff_start: datetime, resolved_filter: bool) -> dict[str, set[str]]:
    """Quét 1 lượt (resolved hoặc chưa resolved), trả về {date_str: set(session_id)}
    cho mọi conversation có updated_at >= cutoff_start."""
    by_date: dict[str, set[str]] = defaultdict(set)
    page = 1
    while page <= MAX_PAGES:
        kwargs = {}
        if resolved_filter:
            kwargs["filter_resolved"] = "true"
        try:
            conversations = client.website.search_conversations(website_id, page, **kwargs)
        except Exception as e:
            if "rate_limited" in str(e):
                print(f"    ⏳ Rate limited on page {page}, sleeping 90s...")
                time.sleep(90)
                continue
            elif "token_scope_forbidden" in str(e):
                print("    ⛔ Token thiếu scope. Dừng lượt quét này.")
                break
            else:
                raise
        if not conversations:
            break

        reached_cutoff = False
        for conv in conversations:
            sid = str(conv.get("session_id", ""))
            updated_at = datetime.fromtimestamp(conv.get("updated_at", 0) / 1000, tz=TZ7)
            if updated_at < cutoff_start:
                reached_cutoff = True
                continue
            date_str = updated_at.strftime("%Y-%m-%d")
            by_date[date_str].add(sid)

        if reached_cutoff:
            break
        if page % 20 == 0:
            print(f"    ...page {page}, đã gom {sum(len(v) for v in by_date.values())} conversation")
        page += 1
        time.sleep(0.2)

    return by_date


def _graded_count_from_db(db, date_str: str, website_id: str) -> int:
    total = 0
    for col_name in ("grading_deco", "grading_searchpie"):
        total += db[col_name].count_documents({"date": date_str, "website_id": website_id})
    return total


def main(date_from: str, date_to: str):
    if not ensure_tunnel():
        raise RuntimeError("Không mở được SSH tunnel tới MongoDB")
    db = get_db()

    client = Crisp()
    client.set_tier("plugin")
    client.authenticate(IDENTIFIER, KEY)

    sites = None
    for _ in range(3):
        try:
            sites = client.plugin.list_all_connect_websites(1, False)
            break
        except Exception as e:
            if "rate_limited" in str(e):
                print("⏳ Rate limited (init), sleeping 60s...")
                time.sleep(60)
            else:
                raise
    if not sites:
        print("❌ Không lấy được danh sách site")
        return

    cutoff_start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=TZ7)

    for site in sites:
        website_id = str(site["website_id"])
        site_name = site.get("name", "Unknown Site")
        print(f"🌐 Site: {site_name} ({website_id})")

        merged: dict[str, set[str]] = defaultdict(set)
        for resolved_filter in [True, False]:
            print(f"  Quét resolved_filter={resolved_filter}...")
            partial = _sweep(client, website_id, cutoff_start, resolved_filter)
            for d, sids in partial.items():
                merged[d] |= sids

        dates_in_range = sorted(d for d in merged if date_from <= d <= date_to)
        print(f"  Tìm thấy dữ liệu cho {len(dates_in_range)} ngày trong khoảng yêu cầu")

        for date_str in dates_in_range:
            total_fetched = len(merged[date_str])
            graded_count = _graded_count_from_db(db, date_str, website_id)
            upsert_stats(
                date_str, website_id, site_name, source="backfill",
                total_fetched=total_fetched, graded_count=graded_count,
            )
            print(f"    {date_str}: fetched={total_fetched} graded={graded_count}")

    print("✅ Done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    main(args.date_from, args.date_to)
