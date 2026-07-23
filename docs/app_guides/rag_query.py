"""CLI test nhanh cho rag.search() — xem knowledge base trả về gì cho 1 câu hỏi cụ thể.

Dùng:
    python docs/app_guides/rag_query.py DECO "how do I create a text badge"
    python docs/app_guides/rag_query.py SearchPie "how to fix broken links" --top_k 5
"""
import sys
import argparse

from rag import search

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app", choices=["DECO", "SearchPie"])
    parser.add_argument("query")
    parser.add_argument("--top_k", type=int, default=4)
    args = parser.parse_args()

    results = search(args.app, args.query, top_k=args.top_k)
    if not results:
        print("(không tìm thấy chunk nào đủ liên quan)")
        sys.exit(0)

    for i, r in enumerate(results, 1):
        tag = f"  [EXPANDED from {r['expanded_from']}]" if r.get("expanded_from") else ""
        print(f"\n=== #{i}  score={r['score']:.3f}  {r['title']} > {r['heading']}{tag} ===")
        print(r["text"][:500] + ("..." if len(r["text"]) > 500 else ""))
        if r["related_pages"]:
            print(f"  related: {', '.join(p['title'] for p in r['related_pages'][:5])}")
