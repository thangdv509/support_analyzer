"""Lưu file .md gốc của knowledge base (DECO Guidelines / SearchPie Docs) vào MongoDB —
tách biệt với việc build embedding index (rag_build_index.py), chỉ lưu nội dung gốc để
tra cứu/backup/dùng cho việc khác sau này.

Collection:
    deco_docs      <- docs/app_guides/deco_guidelines/*.md
    searchpie_docs <- docs/app_guides/searchpie_docs/*.md

Schema mỗi document (upsert theo source_file, chạy lại an toàn khi docs có update):
{
    source_file: str        (tên file không đuôi .md — unique key)
    title:       str        (heading H1 đầu file)
    content:     str        (toàn bộ nội dung file .md gốc, gồm cả mục "Related pages")
    app:         str        ("DECO" | "SearchPie")
    updated_at:  datetime
}

Chạy: python docs/app_guides/save_docs_to_db.py
"""
import os
import re
import sys
import glob
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from database.tunnel import ensure_tunnel
from database.connection import get_db

BASE_DIR = os.path.dirname(__file__)

SITES = [
    {"folder": "deco_guidelines", "app": "DECO", "collection": "deco_docs"},
    {"folder": "searchpie_docs", "app": "SearchPie", "collection": "searchpie_docs"},
]


def _now():
    return datetime.now(timezone.utc)


def save_folder_to_collection(folder: str, app: str, collection: str) -> int:
    col = get_db()[collection]
    col.create_index("source_file", unique=True, background=True)

    md_files = sorted(glob.glob(os.path.join(BASE_DIR, folder, "*.md")))
    count = 0
    for path in md_files:
        source_file = os.path.splitext(os.path.basename(path))[0]
        content = open(path, encoding="utf-8").read()
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else source_file

        col.update_one(
            {"source_file": source_file},
            {"$set": {
                "source_file": source_file,
                "title": title,
                "content": content,
                "app": app,
                "updated_at": _now(),
            }},
            upsert=True,
        )
        count += 1
    return count


if __name__ == "__main__":
    if not ensure_tunnel():
        raise RuntimeError("Không mở được SSH tunnel tới MongoDB — kiểm tra lại .env")

    for site in SITES:
        n = save_folder_to_collection(site["folder"], site["app"], site["collection"])
        print(f"[{site['app']}] đã lưu {n} file vào collection '{site['collection']}'")
