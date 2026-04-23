"""
Dọn dẹp file crawl JSON, bỏ các fields không cần cho phân tích chat.
Usage: python clean_crawl.py crawl_20260226_20260325.json
"""

import json
import sys
import os


def clean_participant(p):
    keep = {"nickname", "user_id", "role", "email", "data"}
    out = {k: v for k, v in p.items() if k in keep and v not in (None, "", [])}
    # Giữ country từ device.geolocation nếu có
    device = p.get("device") or {}
    geo = device.get("geolocation") or {}
    if geo.get("country"):
        out["country"] = geo["country"]
    return out


def clean_message(m):
    keep = {"type", "from", "content", "timestamp", "read", "user"}
    out = {k: v for k, v in m.items() if k in keep and v not in (None, "", [], {})}
    # user: chỉ giữ nickname + user_id
    if "user" in out and isinstance(out["user"], dict):
        u = out["user"]
        out["user"] = {k: v for k, v in u.items() if k in ("nickname", "user_id") and v}
    return out


def clean_conversation(conv):
    drop_keys = {"people_id", "status", "availability", "mentions",
                 "assignees", "unread", "waiting_since", "operators_list"}
    out = {k: v for k, v in conv.items() if k not in drop_keys}

    if "user_participants" in out:
        out["user_participants"] = [clean_participant(p) for p in out["user_participants"]]

    if "messages" in out:
        out["messages"] = [clean_message(m) for m in out["messages"]]

    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: python clean_crawl.py <input.json>")
        sys.exit(1)

    src = sys.argv[1]
    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    cleaned = [clean_conversation(c) for c in data]

    base = os.path.splitext(src)[0]
    out = f"{base}_clean.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    src_size  = os.path.getsize(src) / 1024 / 1024
    out_size  = os.path.getsize(out) / 1024 / 1024
    print(f"✅ {len(cleaned)} conversations → {out}")
    print(f"   {src_size:.1f} MB → {out_size:.1f} MB ({(1 - out_size/src_size)*100:.0f}% nhỏ hơn)")


if __name__ == "__main__":
    main()
