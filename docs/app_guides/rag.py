"""Retrieval cho knowledge base (DECO Guidelines / SearchPie Docs) — semantic search bằng
embedding, dùng để bơm context thật vào prompt LLM thay vì để model tự bịa.

Index được build sẵn bằng rag_build_index.py (docs/app_guides/<app>_index.json).

Module này độc lập, không phụ thuộc code chatbot nào — import trực tiếp `search()` từ
bất cứ đâu cần tra cứu knowledge base (vd chatbot ở project khác, hoặc script phân tích QA).
"""
import os
import json
import requests
import numpy as np
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = "openai/text-embedding-3-small"
BASE_DIR = os.path.dirname(__file__)

# Map tên app -> file index tương ứng
APP_TO_INDEX_FILE = {
    "DECO": "deco_guidelines_index.json",
    "SearchPie": "searchpie_docs_index.json",
}

MIN_SIMILARITY = 0.25  # dưới ngưỡng này coi như không liên quan, không trả về

_index_cache: dict[str, dict] = {}


def _load_index(app_name: str) -> dict | None:
    if app_name in _index_cache:
        return _index_cache[app_name]

    filename = APP_TO_INDEX_FILE.get(app_name)
    if not filename:
        return None
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return None

    records = json.load(open(path, encoding="utf-8"))
    matrix = np.array([r["embedding"] for r in records], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    normalized = matrix / norms

    loaded = {"records": records, "normalized": normalized}
    _index_cache[app_name] = loaded
    return loaded


def _embed_query(text: str) -> np.ndarray:
    r = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=30,
    )
    r.raise_for_status()
    return np.array(r.json()["data"][0]["embedding"], dtype=np.float32)


def _title_lookup(records: list[dict]) -> dict:
    lookup = {}
    for r in records:
        lookup.setdefault(r["source_file"], r["title"])
    return lookup


def _to_result(rec: dict, score: float) -> dict:
    return {
        "source_file": rec["source_file"],
        "title": rec["title"],
        "heading": rec["heading"],
        "text": rec["text"],
        "score": score,
        "parent": rec.get("parent"),
        "siblings": rec.get("siblings", []),
    }


def search(app_name: str, query: str, top_k: int = 4, expand_parent: bool = True, max_expansions: int = 2) -> list[dict]:
    """Trả về top_k chunk liên quan nhất tới `query` trong knowledge base của `app_name`.
    Trả [] nếu app không có knowledge base, query rỗng, hoặc không có chunk nào đủ liên quan.

    Mỗi kết quả kèm `related_pages` (trang cha/anh em, suy ra từ build_wiki_links.py) để
    consumer có thể dẫn thêm link/tra cứu sâu hơn nếu cần.

    Nếu `expand_parent=True`: khi 1 chunk khớp thuộc 1 trang con (vd "TEXT BADGE") mà trang
    cha của nó (vd "DECO Product Badges") chưa nằm trong top_k, tự động kéo thêm 1 chunk khớp
    nhất của trang cha vào — giúp LLM có đủ ngữ cảnh tổng quan, không chỉ mỗi chi tiết con.
    Tối đa `max_expansions` chunk được kéo thêm kiểu này (tránh làm phình prompt).
    """
    if not query or not query.strip():
        return []

    index = _load_index(app_name)
    if index is None:
        return []

    query_vec = _embed_query(query)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return []
    query_vec = query_vec / query_norm

    scores = index["normalized"] @ query_vec
    order = np.argsort(-scores)

    results = []
    seen_source_files = set()
    for i in order:
        if len(results) >= top_k:
            break
        score = float(scores[i])
        if score < MIN_SIMILARITY:
            break  # order giảm dần -> dưới ngưỡng thì các phần tử sau cũng vậy
        rec = index["records"][i]
        seen_source_files.add(rec["source_file"])
        results.append(_to_result(rec, score))

    if expand_parent:
        expansions = 0
        for rec in list(results):
            parent = rec.get("parent")
            if not parent or parent in seen_source_files or expansions >= max_expansions:
                continue
            candidates = [j for j, r in enumerate(index["records"]) if r["source_file"] == parent]
            if not candidates:
                continue
            best_j = max(candidates, key=lambda j: scores[j])
            if scores[best_j] < MIN_SIMILARITY * 0.6:
                continue
            parent_rec = index["records"][best_j]
            expanded = _to_result(parent_rec, float(scores[best_j]))
            expanded["expanded_from"] = rec["source_file"]
            results.append(expanded)
            seen_source_files.add(parent)
            expansions += 1

    title_lookup = _title_lookup(index["records"])
    for r in results:
        r["related_pages"] = [
            {"filename": fn, "title": title_lookup.get(fn, fn)} for fn in r.pop("siblings", [])
        ]
    return results
