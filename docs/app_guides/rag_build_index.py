"""Build embedding index cho knowledge base (DECO Guidelines + SearchPie Docs).

Chunk mỗi file .md trong docs/app_guides/<app>/ theo heading markdown (## / ###),
embed bằng OpenRouter (model openai/text-embedding-3-small, cùng OPENROUTER_API_KEY
đang dùng cho các phần khác của project), lưu ra docs/app_guides/<app>_index.json.

Chạy lại khi knowledge base có update (vd crawl_gitbook.py chạy lại lấy docs mới):
    python docs/app_guides/rag_build_index.py
"""
import os
import re
import json
import glob

import requests
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
EMBEDDING_MODEL = "openai/text-embedding-3-small"
BASE_DIR = os.path.dirname(__file__)

APPS = {
    "deco_guidelines": "DECO",
    "searchpie_docs": "SearchPie",
}

_HEADING_RE = re.compile(r"^#{1,3}\s+.+$", re.MULTILINE)
MAX_CHUNK_CHARS = 1500


def _split_into_chunks(md_text: str) -> list[dict]:
    """Cắt theo heading (## / ###); nếu 1 section vẫn quá dài thì cắt tiếp theo đoạn văn."""
    matches = list(_HEADING_RE.finditer(md_text))
    if not matches:
        sections = [("", md_text)]
    else:
        sections = []
        first_heading_start = matches[0].start()
        if first_heading_start > 0:
            sections.append(("", md_text[:first_heading_start]))
        for i, m in enumerate(matches):
            heading = m.group().lstrip("#").strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
            sections.append((heading, md_text[start:end]))

    chunks = []
    for heading, body in sections:
        body = body.strip()
        if not body:
            continue
        pieces = [body] if len(body) <= MAX_CHUNK_CHARS else _split_long_text(body)
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            chunks.append({"heading": heading, "text": piece})
    return chunks


def _split_long_text(text: str) -> list[str]:
    paragraphs = text.split("\n\n")
    pieces, current = [], ""
    for p in paragraphs:
        if len(current) + len(p) + 2 <= MAX_CHUNK_CHARS:
            current = f"{current}\n\n{p}" if current else p
        else:
            if current:
                pieces.append(current)
            current = p
    if current:
        pieces.append(current)
    return pieces


def _embed_batch(texts: list[str]) -> list[list[float]]:
    r = requests.post(
        "https://openrouter.ai/api/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "input": texts},
        timeout=60,
    )
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]


def _load_manifest(folder_name: str) -> dict:
    path = os.path.join(BASE_DIR, f"{folder_name}_manifest.json")
    if not os.path.exists(path):
        return {}
    return json.load(open(path, encoding="utf-8"))


def build_index_for_app(folder_name: str, app_name: str) -> None:
    folder = os.path.join(BASE_DIR, folder_name)
    md_files = sorted(glob.glob(os.path.join(folder, "*.md")))
    manifest = _load_manifest(folder_name)
    if not manifest:
        print(f"  ⚠ chưa có {folder_name}_manifest.json — chạy build_wiki_links.py trước để có"
              f" breadcrumb/related pages. Vẫn build index nhưng thiếu liên kết.")

    records = []
    for path in md_files:
        source_file = os.path.splitext(os.path.basename(path))[0]
        text = open(path, encoding="utf-8").read()
        # Bỏ section "## Related pages" tự sinh (build_wiki_links.py) — chỉ để điều hướng,
        # không phải nội dung, không nên embed/chunk.
        text = text.split("<!-- wiki-links:auto-generated")[0].rstrip()
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else source_file
        page_links = manifest.get(source_file, {})

        for chunk in _split_into_chunks(text):
            embed_input = f"{title}"
            if chunk["heading"] and chunk["heading"] != title:
                embed_input += f" > {chunk['heading']}"
            embed_input += f"\n\n{chunk['text']}"
            records.append({
                "app": app_name,
                "source_file": source_file,
                "title": title,
                "heading": chunk["heading"],
                "text": chunk["text"],
                "parent": page_links.get("parent"),
                "siblings": page_links.get("siblings", []),
                "children": page_links.get("children", []),
                "embed_input": embed_input,
            })

    print(f"[{app_name}] {len(md_files)} file -> {len(records)} chunk")

    BATCH = 50
    for i in range(0, len(records), BATCH):
        batch = records[i:i + BATCH]
        embeddings = _embed_batch([r["embed_input"] for r in batch])
        for rec, emb in zip(batch, embeddings):
            rec["embedding"] = emb
            del rec["embed_input"]
        print(f"  embedded {min(i + BATCH, len(records))}/{len(records)}")

    out_path = os.path.join(BASE_DIR, f"{folder_name}_index.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    print(f"  -> saved {out_path}")


if __name__ == "__main__":
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Missing OPENROUTER_API_KEY in .env")
    for folder_name, app_name in APPS.items():
        build_index_for_app(folder_name, app_name)
