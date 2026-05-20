"""
reexport_sheet.py — Xuất lại Support Analyzer sheet, load-or-grade từng ngày.

Với mỗi ngày trong khoảng:
  - Đã có trong MongoDB → lấy ra dùng ngay (không chấm lại)
  - Chưa có              → fetch Crisp → chấm LLM → lưu MongoDB → xuất

Sau khi load/grade xong toàn bộ: xóa sheet rồi ghi lại đúng format.

Chạy:
    python reexport_sheet.py --from 2026-05-03 --to 2026-05-18
    python reexport_sheet.py --from 2026-05-03        # đến hôm nay
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import gspread
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
)
from database.tunnel import ensure_tunnel
from database.deco_chat import get_chats_by_date
from scheduler import _export_to_support_analyzer, _save_to_mongo, SHEET_NAME


def _load_or_grade_date(date_str: str) -> list[dict]:
    """
    Trả về danh sách chat đã chấm cho ngày date_str.
    - Nếu đã có trong MongoDB: dùng luôn, không chấm lại.
    - Nếu chưa có: fetch Crisp → chấm → lưu MongoDB → trả về.
    """
    existing = get_chats_by_date(date_str)
    if existing:
        print(f"  📦 {len(existing)} chats (MongoDB)")
        return existing

    print(f"  🔍 Chưa có trong DB, đang fetch Crisp...")
    chats = fetch_chats(date_str)
    if not chats:
        return []

    print(f"  ⚖️  {len(chats)} chats mới, đang chấm...")
    results = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(_grade_one, (i + 1, len(chats), c)): c for i, c in enumerate(chats)}
        for fut in as_completed(futs):
            r = fut.result()
            if r:
                results.append(r)

    if results:
        _save_to_mongo(results)

    return results


def _reset_sheet():
    """Xóa hẳn sheet và tạo lại để đảm bảo clean state (xóa cả content lẫn formatting cũ)."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
        spreadsheet.del_worksheet(ws)
        print(f"🗑  Deleted sheet '{SHEET_NAME}'")
    except gspread.WorksheetNotFound:
        pass
    spreadsheet.add_worksheet(title=SHEET_NAME, rows=2000, cols=25)
    print(f"✅ Recreated sheet '{SHEET_NAME}'")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", required=True,
                        help="Ngày bắt đầu (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to",
                        default=datetime.now().strftime("%Y-%m-%d"),
                        help="Ngày kết thúc (YYYY-MM-DD), mặc định hôm nay")
    args = parser.parse_args()

    d_from = datetime.strptime(args.date_from, "%Y-%m-%d")
    d_to   = datetime.strptime(args.date_to,   "%Y-%m-%d")
    if d_from > d_to:
        print("❌ --from phải trước --to.")
        return

    total_days = (d_to - d_from).days + 1
    print(f"📅 {args.date_from} → {args.date_to} ({total_days} ngày)")
    print("=" * 55)

    load_few_shot_examples()
    ensure_tunnel()

    t0 = time.time()
    all_results: list[dict] = []
    skipped_empty = 0
    current = d_from

    while current <= d_to:
        date_str = current.strftime("%Y-%m-%d")
        day_num  = (current - d_from).days + 1
        print(f"\n[{day_num}/{total_days}] {date_str}", end=" — ")

        results = _load_or_grade_date(date_str)
        if results:
            all_results.extend(results)
        else:
            skipped_empty += 1
            print("  không có chat")

        current += timedelta(days=1)

    print(f"\n{'=' * 55}")
    print(f"📊 Tổng: {len(all_results)} chats ({total_days - skipped_empty} ngày có data, {skipped_empty} ngày trống)")
    print(f"⏱  Load/grade: {_fmt_elapsed(time.time() - t0)}")

    if not all_results:
        print("Không có data để xuất.")
        return

    _reset_sheet()

    print(f"\n📋 Đang xuất {len(all_results)} records ra sheet '{SHEET_NAME}'...")
    _export_to_support_analyzer(all_results)

    print(f"⏱  Tổng: {_fmt_elapsed(time.time() - t0)}")


if __name__ == "__main__":
    main()
