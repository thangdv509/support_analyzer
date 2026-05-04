"""
export_history.py — Xuất toàn bộ lịch sử chấm điểm vào 1 sheet Google Sheets.

Ưu tiên dùng data đã có trong MongoDB (không chấm lại, nhanh).
Ngày nào chưa có trong MongoDB sẽ fetch từ Crisp API và chấm mới.

Chạy:
    python export_history.py --from 2026-01-01
    python export_history.py --from 2026-01-01 --to 2026-04-15
    python export_history.py --from 2026-01-01 --sheet "History Q1 2026"
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

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
from main import _export_to_gsheet, _save_to_mongo

load_dotenv()


def _load_or_grade_date(date_str: str) -> list[dict]:
    """
    Trả về danh sách chat đã chấm cho ngày date_str.
    - Nếu đã có trong MongoDB: dùng luôn, không chấm lại.
    - Nếu chưa có: fetch từ Crisp → chấm → lưu MongoDB → trả về.
    """
    existing = get_chats_by_date(date_str)
    if existing:
        print(f"  📦 {len(existing)} chats (MongoDB cache)")
        return existing

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


def _delete_sheet_if_exists(sheet_name: str):
    """Xóa sheet cũ nếu đã tồn tại để tạo lại từ đầu."""
    if not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        return
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    try:
        spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
        ws = spreadsheet.worksheet(sheet_name)
        spreadsheet.del_worksheet(ws)
        print(f"  🗑️  Đã xóa sheet cũ '{sheet_name}'")
    except gspread.WorksheetNotFound:
        pass
    except Exception as e:
        print(f"  ⚠️  Không xóa được sheet cũ: {e}")


def main():
    parser = argparse.ArgumentParser(description="Xuất lịch sử QA vào Google Sheets")
    parser.add_argument("--from", dest="date_from", required=True, help="Ngày bắt đầu (YYYY-MM-DD)")
    parser.add_argument("--to",   dest="date_to",   default=datetime.now().strftime("%Y-%m-%d"),
                        help="Ngày kết thúc (YYYY-MM-DD), mặc định hôm nay")
    parser.add_argument("--sheet", default=None,
                        help="Tên sheet, mặc định 'History YYYY'")
    parser.add_argument("--no-mongo", action="store_true", help="Không lưu MongoDB (chỉ export sheet)")
    args = parser.parse_args()

    d_from = datetime.strptime(args.date_from, "%Y-%m-%d")
    d_to   = datetime.strptime(args.date_to,   "%Y-%m-%d")
    if d_from > d_to:
        print("❌ --from phải trước --to.")
        return

    sheet_name  = args.sheet or f"History {d_from.year}"
    total_days  = (d_to - d_from).days + 1

    print(f"📅 {args.date_from} → {args.date_to} ({total_days} ngày) | Sheet: '{sheet_name}'")
    print("=" * 55)

    load_few_shot_examples()
    if not args.no_mongo:
        ensure_tunnel()

    t0 = time.time()
    all_results: list[dict] = []
    current = d_from
    day_num = 0
    skipped_empty = 0

    while current <= d_to:
        date_str = current.strftime("%Y-%m-%d")
        day_num += 1
        print(f"\n[{day_num}/{total_days}] {date_str}", end=" — ")

        results = _load_or_grade_date(date_str)
        if results:
            all_results.extend(results)
        else:
            skipped_empty += 1
            print("không có chat")

        current += timedelta(days=1)

    print(f"\n{'=' * 55}")
    print(f"📊 Tổng: {len(all_results)} chats ({total_days - skipped_empty} ngày có data, {skipped_empty} ngày trống)")
    print(f"⏱  Load/grade: {_fmt_elapsed(time.time() - t0)}")

    if not all_results:
        print("Không có data để xuất.")
        return

    print(f"\n📋 Đang xuất ra sheet '{sheet_name}'...")
    _delete_sheet_if_exists(sheet_name)
    _export_to_gsheet(all_results, sheet_name)

    print(f"⏱  Tổng: {_fmt_elapsed(time.time() - t0)}")


if __name__ == "__main__":
    main()
