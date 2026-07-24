"""Crawl stats — số conversation Crisp THẬT fetch được mỗi ngày/site (trước khi lọc/chấm),
để đối chiếu "Tổng QA chats" (số đã chấm, lưu trong grading_deco/grading_searchpie) với số
thật trên Crisp — vì pipeline chấm điểm chủ động loại bỏ 1 số conversation không đạt yêu cầu
(xem analyzer_v2.py:fetch_chats — drop_no_msgs/no_segment/no_ops/not_completed/too_short).

Collection: crawl_stats
Unique key: (date, website_id)
Schema:
{
    date:               str   ("YYYY-MM-DD")
    website_id:         str
    site_name:          str   (tên site Crisp — mỗi site tương ứng 1 app)
    total_fetched:       int   (số conversation Crisp trả về cho ngày đó, TRƯỚC khi lọc)
    graded_count:       int | None  (số conversation thực sự được chấm — None nếu chỉ backfill đếm, không re-grade)
    drop_no_msgs:       int | None
    drop_no_segment:    int | None
    drop_no_ops:        int | None
    drop_not_completed: int | None
    drop_too_short:     int | None
    source:             str   ("live" | "backfill")
    updated_at:         datetime
}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .connection import get_db

_COL = "crawl_stats"


def _col():
    col = get_db()[_COL]
    col.create_index([("date", 1), ("website_id", 1)], unique=True, background=True)
    return col


def upsert_stats(date: str, website_id: str, site_name: str, source: str, **fields: Any) -> None:
    doc = {
        "date": date,
        "website_id": website_id,
        "site_name": site_name,
        "source": source,
        "updated_at": datetime.now(timezone.utc),
        **fields,
    }
    _col().update_one({"date": date, "website_id": website_id}, {"$set": doc}, upsert=True)


def get_stats(date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    query: dict[str, Any] = {}
    if date_from and date_to:
        query["date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        query["date"] = {"$gte": date_from}
    elif date_to:
        query["date"] = {"$lte": date_to}
    return list(_col().find(query))
