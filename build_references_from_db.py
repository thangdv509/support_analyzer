"""
build_references_from_db.py — Tạo qa_references.json từ MongoDB.

Thay thế build_references.py (không cần CSV, không cần gọi Crisp API).
Chọn các ví dụ đại diện từ dữ liệu đã chấm điểm có sẵn trong DB.

Chạy:
    python build_references_from_db.py
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from pymongo import DESCENDING

from database.tunnel import ensure_tunnel
from database.connection import get_db

load_dotenv()

_SCORE_CAPS = {
    "greetings": 0.25, "grammar": 1.25, "communication": 2.0, "listening": 1.5,
    "tone_pace": 0.75, "empathy": 0.75, "enthusiastic": 1.5, "probing": 1.5,
    "solution": 3.0, "proactiveness": 2.0, "transferring": 2.0, "resources": 0.5,
    "extra_mile": 1.5, "review_asking": 1.5,
}

OUTPUT_PATH = Path(__file__).resolve().parent / "qa_references.json"


def _deductions(criteria: dict) -> dict:
    return {
        k: {"got": v.get("score", 0), "max": _SCORE_CAPS[k]}
        for k, v in criteria.items()
        if k in _SCORE_CAPS and float(v.get("score", 0)) < _SCORE_CAPS[k]
    }


def select_examples(docs: list[dict], pool_size: int = 5) -> list[dict]:
    """Chọn tối đa pool_size examples cho mỗi label."""
    selected = []
    used: set[str] = set()

    def pick_n(label: str, filter_fn, n: int = pool_size):
        count = 0
        for doc in docs:
            if count >= n:
                break
            sid = doc["session_id"]
            if sid in used:
                continue
            criteria = doc.get("grading", {}).get("criteria", {})
            if len(criteria) < 14:
                continue
            transcript = doc.get("transcript", "")
            if len(transcript) < 200:
                continue
            deduct = _deductions(criteria)
            if filter_fn(deduct, criteria):
                selected.append({
                    "session_id": sid,
                    "label":      label,
                    "date":       doc.get("date"),
                    "agent":      doc.get("primary_operator"),
                    "app":        doc.get("app"),
                    "transcript": transcript,
                    "expected_output": {
                        "criteria":        criteria,
                        "overall_summary": doc["grading"].get("overall_summary", ""),
                    },
                    "deductions": deduct,
                })
                used.add(sid)
                count += 1
        deduct_str = "⚠️  Không tìm được" if count == 0 else f"{count} examples"
        print(f"  [{label}] {deduct_str}")

    pick_n("perfect_10",
           lambda d, c: len(d) == 0)

    pick_n("solution_zero",
           lambda d, c: float(c.get("solution", {}).get("score", 1)) == 0)

    pick_n("review_only",
           lambda d, c: set(d.keys()) == {"review_asking"})

    pick_n("transferring_zero",
           lambda d, c: float(c.get("transferring", {}).get("score", 1)) == 0)

    pick_n("solution_deducted",
           lambda d, c: "solution" in d and len(d) == 1
                        and float(c.get("solution", {}).get("score", 3)) <= 1.5)

    pick_n("communication_deducted",
           lambda d, c: "communication" in d
                        and float(c.get("communication", {}).get("score", 2)) <= 1.0)

    return selected


def main():
    print("🔌 Kết nối MongoDB...")
    ensure_tunnel()
    col = get_db()["deco_chat"]

    total = col.count_documents({})
    print(f"📦 {total} documents trong DB")

    print("📂 Đang load graded documents...")
    docs = list(col.find(
        {"grading.criteria": {"$exists": True}},
        {"session_id": 1, "date": 1, "app": 1, "primary_operator": 1,
         "transcript": 1, "grading": 1},
    ).sort("date", DESCENDING))  # ưu tiên data mới nhất
    print(f"  → {len(docs)} documents có grading data")

    print("\n🎯 Chọn examples:")
    examples = select_examples(docs)

    if not examples:
        print("❌ Không chọn được ví dụ nào.")
        return

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(examples, f, ensure_ascii=False, indent=2)

    # Thống kê theo label
    from collections import Counter
    counts = Counter(e["label"] for e in examples)
    print(f"\n✅ Saved {len(examples)} examples → {OUTPUT_PATH}")
    for label, cnt in counts.most_common():
        print(f"  {label}: {cnt} examples")


if __name__ == "__main__":
    main()
