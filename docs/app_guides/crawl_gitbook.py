"""One-off script: crawl DECO Guidelines + SearchPie Docs (cả 2 đều là GitBook) thành .md
local, đặt tên file theo breadcrumb (nối các segment URL bằng "_", bỏ số thứ tự + dấu gạch).

GitBook expose sẵn bản Markdown thô của mỗi trang bằng cách thêm ".md" vào URL, và có
"llms.txt" liệt kê đầy đủ toàn bộ trang (title + link) — dùng làm index thay vì tự crawl link
trong HTML.

Chạy: python docs/app_guides/crawl_gitbook.py
"""
import os
import re
import time
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

SITES = [
    {
        "name": "DECO Guidelines",
        "base_url": "https://deco-product-labels-and-badges-1.gitbook.io/deco-guidelines",
        "out_dir": os.path.join(os.path.dirname(__file__), "deco_guidelines"),
    },
    {
        "name": "SearchPie Docs",
        "base_url": "https://docs.searchpie.io",
        "out_dir": os.path.join(os.path.dirname(__file__), "searchpie_docs"),
    },
]

_LLMS_LINE_RE = re.compile(r"^- \[(.*?)\]\((.*?)\)(?::\s*(.*))?$")


def fetch_llms_links(base_url: str) -> list[dict]:
    r = requests.get(f"{base_url}/llms.txt", headers=HEADERS, timeout=30)
    r.raise_for_status()
    links = []
    for line in r.text.splitlines():
        m = _LLMS_LINE_RE.match(line.strip())
        if not m:
            continue
        title, url, desc = m.groups()
        links.append({"title": title, "url": url, "desc": desc or ""})
    return links


def _slugify_segment(seg: str) -> str:
    seg = re.sub(r"^\d+-", "", seg)         # bỏ số thứ tự đầu (vd "1-text-badge" -> "text-badge")
    seg = re.sub(r"[^a-zA-Z0-9]", "", seg)  # bỏ dấu gạch ngang/chấm...
    return seg.lower()


def path_to_filename(md_url: str, base_url: str) -> str:
    path = md_url[len(base_url):].strip("/")
    if path.endswith(".md"):
        path = path[:-3]
    segments = [s for s in path.split("/") if s]
    return "_".join(_slugify_segment(s) for s in segments) + ".md"


def _strip_boilerplate(md_text: str) -> str:
    """Bỏ đoạn blockquote disclaimer GitBook tự chèn đầu mỗi trang .md."""
    lines = md_text.splitlines()
    idx = 0
    while idx < len(lines) and (lines[idx].strip() == "" or lines[idx].lstrip().startswith(">")):
        idx += 1
    return "\n".join(lines[idx:]).strip() + "\n"


def crawl_site(site: dict) -> None:
    os.makedirs(site["out_dir"], exist_ok=True)
    links = fetch_llms_links(site["base_url"])
    print(f"[{site['name']}] {len(links)} trang tìm thấy trong llms.txt")

    for link in links:
        fname = path_to_filename(link["url"], site["base_url"])
        out_path = os.path.join(site["out_dir"], fname)

        for attempt in range(2):
            try:
                resp = requests.get(link["url"], headers=HEADERS, timeout=30)
                resp.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 1:
                    print(f"  ✗ FAILED {link['url']}: {e}")
                    resp = None
                else:
                    time.sleep(1)
        if resp is None:
            continue

        content = _strip_boilerplate(resp.text)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ {fname}  ({len(content)} chars)  <- {link['title']}")
        time.sleep(0.3)


if __name__ == "__main__":
    for site in SITES:
        crawl_site(site)
