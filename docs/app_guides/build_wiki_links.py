"""Suy ra quan hệ liên kết wiki (breadcrumb/parent, related pages/siblings, prev/next) giữa
các trang đã crawl — dựa thuần vào thứ tự + URL path trong llms.txt (chính là thứ tự sidebar
gốc của GitBook), không cần crawl lại HTML.

Output:
  - docs/app_guides/<folder>_manifest.json — quan hệ giữa các trang, để rag_build_index.py
    đọc và đính kèm vào từng chunk.
  - Ghi thêm mục "## Related pages" vào cuối mỗi file .md (breadcrumb + related + prev/next),
    để đọc trực tiếp file .md cũng thấy được liên kết, không chỉ qua index.json.

Chạy SAU crawl_gitbook.py (cần .md đã có sẵn), TRƯỚC rag_build_index.py:
    python docs/app_guides/build_wiki_links.py
"""
import os
import re
import json
from collections import defaultdict

import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}
BASE_DIR = os.path.dirname(__file__)

SITES = [
    {
        "folder": "deco_guidelines",
        "base_url": "https://deco-product-labels-and-badges-1.gitbook.io/deco-guidelines",
    },
    {
        "folder": "searchpie_docs",
        "base_url": "https://docs.searchpie.io",
    },
]

_LLMS_LINE_RE = re.compile(r"^- \[(.*?)\]\((.*?)\)(?::\s*(.*))?$")
_MARKER = "\n\n---\n\n<!-- wiki-links:auto-generated, xem build_wiki_links.py -->\n"


def _fetch_llms_links(base_url: str) -> list[dict]:
    r = requests.get(f"{base_url}/llms.txt", headers=HEADERS, timeout=30)
    r.raise_for_status()
    links = []
    for line in r.text.splitlines():
        m = _LLMS_LINE_RE.match(line.strip())
        if not m:
            continue
        title, url, desc = m.groups()
        links.append({"title": title, "url": url})
    return links


def _slugify_segment(seg: str) -> str:
    seg = re.sub(r"^\d+-", "", seg)
    seg = re.sub(r"[^a-zA-Z0-9]", "", seg)
    return seg.lower()


def _path_segments(md_url: str, base_url: str) -> list[str]:
    path = md_url[len(base_url):].strip("/")
    if path.endswith(".md"):
        path = path[:-3]
    return [s for s in path.split("/") if s]


def _filename(segments: list[str]) -> str:
    return "_".join(_slugify_segment(s) for s in segments)


def build_manifest(base_url: str) -> dict:
    links = _fetch_llms_links(base_url)
    pages = []
    for order_index, link in enumerate(links):
        segments = _path_segments(link["url"], base_url)
        pages.append({
            "filename": _filename(segments),
            "title": link["title"],
            "segments": segments,
            "order_index": order_index,
        })

    filename_set = {p["filename"] for p in pages}

    # Parent thật = bỏ dần segment cuối tới khi khớp 1 trang có thật (bỏ qua các segment chỉ
    # là group/category trong sidebar, không phải trang thật, vd "our-features").
    for p in pages:
        segs = p["segments"]
        p["parent"] = None
        for cut in range(len(segs) - 1, 0, -1):
            candidate = _filename(segs[:cut])
            if candidate in filename_set and candidate != p["filename"]:
                p["parent"] = candidate
                break

    groups = defaultdict(list)
    for p in pages:
        groups[p["parent"]].append(p)
    for group in groups.values():
        group.sort(key=lambda p: p["order_index"])
        for i, p in enumerate(group):
            p["prev"] = group[i - 1]["filename"] if i > 0 else None
            p["next"] = group[i + 1]["filename"] if i < len(group) - 1 else None
            p["siblings"] = [g["filename"] for g in group if g is not p]

    for p in pages:
        p["children"] = [c["filename"] for c in pages if c["parent"] == p["filename"]]

    return {p["filename"]: p for p in pages}


def _append_related_section(md_dir: str, manifest: dict) -> None:
    title_of = {fn: p["title"] for fn, p in manifest.items()}

    def _link(fn: str) -> str:
        return f"[{title_of.get(fn, fn)}]({fn}.md)"

    for filename, p in manifest.items():
        path = os.path.join(md_dir, f"{filename}.md")
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        text = text.split(_MARKER)[0].rstrip() + "\n"  # bỏ section cũ nếu chạy lại

        lines = ["## Related pages"]
        if p["parent"]:
            lines.append(f"- Parent: {_link(p['parent'])}")
        if p["siblings"]:
            sib_links = ", ".join(_link(s) for s in p["siblings"][:8])
            lines.append(f"- Related: {sib_links}")
        if p["children"]:
            child_links = ", ".join(_link(c) for c in p["children"])
            lines.append(f"- Sub-pages: {child_links}")
        if p["prev"] or p["next"]:
            nav = []
            if p["prev"]:
                nav.append(f"« {_link(p['prev'])}")
            if p["next"]:
                nav.append(f"{_link(p['next'])} »")
            lines.append(f"- Nav: {' | '.join(nav)}")

        if len(lines) == 1:
            continue  # không có liên kết nào (trang đơn lẻ) -> khỏi thêm section rỗng

        with open(path, "w", encoding="utf-8") as f:
            f.write(text + _MARKER + "\n".join(lines) + "\n")


def process_site(site: dict) -> None:
    manifest = build_manifest(site["base_url"])
    print(f"[{site['folder']}] {len(manifest)} trang, đã suy ra quan hệ liên kết")

    manifest_path = os.path.join(BASE_DIR, f"{site['folder']}_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"  -> saved {manifest_path}")

    md_dir = os.path.join(BASE_DIR, site["folder"])
    _append_related_section(md_dir, manifest)
    print(f"  -> đã thêm 'Related pages' vào các file .md trong {md_dir}")


if __name__ == "__main__":
    for site in SITES:
        process_site(site)
