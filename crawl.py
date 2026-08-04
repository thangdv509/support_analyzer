"""
Crawl Crisp conversations to JSON — full data, giữ cách extract metadata gốc.
Usage:
  python crawl.py --date 2026-03-20
  python crawl.py --from 2026-03-01 --to 2026-03-20
  python crawl.py --date 2026-03-20 --website 17e47fa7-xxxx
"""

import os
import uuid
import json
import time
import argparse
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

IDENTIFIER        = os.getenv("CRISP_IDENTIFIER")
KEY               = os.getenv("CRISP_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
HEADERS    = {"X-Crisp-Tier": "plugin"}
AUTH       = (IDENTIFIER, KEY)
TZ7        = timezone(timedelta(hours=7))
BASE       = "https://api.crisp.chat/v1"
MODEL      = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

SUMMARY_PROMPT = (
    "You are an AI assistant specialized in summarizing customer support conversations."
    "Analyze the conversation and produce a clear, concise summary that captures:"
    "Key issues or questions raised by the customer:"
    "(e.g., pain points, requests, or problems)"
    "Relevant context and details shared by the customer:"
    "(background information, clarifications, specific examples)"
    "Actions taken or solutions provided by the support agent:"
    "(steps taken during the conversation to resolve the issue)"
    "Any decisions made or agreements reached:"
    "(what was agreed upon between the customer and the agent)"
    "Notable customer sentiment or tone:"
    "(e.g., frustrated, satisfied, neutral)"
    "Present the summary as a well-organized bullet-point list, using clear and professional language suitable for internal tracking or handover."
)


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(path, params=None, retries=5):
    url = path if path.startswith("http") else f"{BASE}{path}"
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, auth=AUTH, params=params, timeout=30)
            if r.status_code == 429:
                wait = 60 + attempt * 30
                print(f"    ⏳ Rate limited, sleeping {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            body = r.json()
            return body.get("data") if "data" in body else body
        except requests.exceptions.RequestException as e:
            print(f"    ❌ {e}")
            if attempt < retries - 1:
                time.sleep(3 + attempt * 2)
    return None


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def fetch_websites():
    all_sites = []
    for page in range(1, 20):
        data = _get(f"/plugin/connect/websites/all/{page}", params={"filter_configured": "false"})
        if not data:
            break
        sites = data if isinstance(data, list) else []
        if not sites:
            break
        all_sites.extend(sites)
        time.sleep(0.2)
    return all_sites


def fetch_operators(website_id):
    data = _get(f"/website/{website_id}/operators/list")
    return data if isinstance(data, list) else []


def fetch_conversations_for_day(website_id, day_start_ms, day_end_ms):
    conv_list = []
    seen = set()
    for resolved_flag in ["false", "true"]:
        for page in range(1, 101):
            data = _get(
                f"/website/{website_id}/conversations/{page}",
                params={"filter_date_start": str(day_start_ms), "filter_resolved": resolved_flag},
            )
            if not data:
                break
            passed = False
            for conv in (data if isinstance(data, list) else []):
                sid = str(conv.get("session_id", ""))
                updated_ms = conv.get("updated_at", 0)
                if updated_ms < day_start_ms:
                    passed = True
                elif updated_ms < day_end_ms and sid not in seen:
                    seen.add(sid)
                    conv_list.append(conv)
            if passed:
                break
            time.sleep(0.2)
    return conv_list


def fetch_all_messages(website_id, session_id):
    """Fetch full message history, tất cả pages, tất cả types."""
    all_msgs = []
    params = {}
    for _ in range(50):
        data = _get(f"/website/{website_id}/conversation/{session_id}/messages/", params=params)
        if not data:
            break
        msgs = data if isinstance(data, list) else []
        if not msgs:
            break
        all_msgs.extend(msgs)
        oldest_ts = min(m.get("timestamp", 0) for m in msgs)
        params = {"timestamp_before": str(oldest_ts)}
        time.sleep(0.2)
    all_msgs.sort(key=lambda m: m.get("timestamp", 0))
    return all_msgs


def split_segments(messages):
    """
    Chia messages thành các segment nhỏ theo sự kiện 'resolved'.
    Mỗi segment là một đợt hội thoại liên tục trước khi được resolved.
    """
    segments = []
    current = []
    for m in messages:
        current.append(m)
        if m.get("type") == "event":
            content = m.get("content", "")
            is_resolved = (
                (isinstance(content, dict) and (
                    content.get("namespace") == "state:resolved" or
                    content.get("type") == "resolved" or
                    content.get("action") == "resolved" or
                    content.get("state") == "resolved"
                )) or str(content) == "resolved"
            )
            if is_resolved:
                segments.append(current)
                current = []
    if current:
        segments.append(current)
    return segments


def _summarize_segment(msgs):
    """Gọi LLM để summary + 3 tags cho một segment. Trả về dict {summary, tags}."""
    chat_msgs = [m for m in msgs if isinstance(m.get("content"), str)
                 and m.get("type") not in ("event", "note", "animation")]
    if not chat_msgs:
        return None
    transcript = "\n".join(
        f"{m.get('user', {}).get('nickname', m.get('from', '?'))}: {m['content']}"
        for m in chat_msgs
    )
    system_prompt = (
        SUMMARY_PROMPT +
        "\n\nAdditionally, at the end of your response return a JSON block in this exact format:\n"
        '```json\n{"tags": ["tag1", "tag2", "tag3"]}\n```\n'
        "The 3 tags must be short (2-4 words each), specific topic labels that best describe this conversation segment."
    )
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": transcript},
            ]},
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()

        # Tách tags JSON ra khỏi summary text
        tags = []
        summary_text = raw
        if "```json" in raw:
            parts = raw.split("```json")
            summary_text = parts[0].strip()
            try:
                tags_raw = parts[1].split("```")[0].strip()
                tags = json.loads(tags_raw).get("tags", [])
            except Exception:
                pass

        return {"summary": summary_text, "tags": tags}
    except Exception as e:
        print(f" [summary error: {e}]", end="")
        return None


def summarize_conversation(messages):
    """Chia conversation thành segments, summary từng segment kèm 3 tags."""
    if not OPENROUTER_API_KEY:
        return None
    segments = split_segments(messages)
    results = []
    for idx, seg_msgs in enumerate(segments, 1):
        result = _summarize_segment(seg_msgs)
        if result:
            # Lấy thời gian đầu/cuối của segment
            ts_list = [m.get("timestamp") for m in seg_msgs if m.get("timestamp")]
            seg_out = {
                "segment":  idx,
                "tags":     result["tags"],
                "summary":  result["summary"],
            }
            if ts_list:
                seg_out["start"] = datetime.fromtimestamp(min(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S")
                seg_out["end"]   = datetime.fromtimestamp(max(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S")
            results.append(seg_out)
    return results if results else None


# ── Deterministic UUID ───────────────────────────────────────────────────────

_NS = uuid.UUID("b7e2a1c4-4f3d-5e6a-8b9c-0d1e2f3a4b5c")  # namespace cố định

def conv_uuid(session_id: str) -> str:
    """UUID tất định từ session_id (đã unique). Encode lại cùng input → cùng UUID."""
    return str(uuid.uuid5(_NS, session_id))


# ── Extract — giữ cách gốc từ crawl_data.py ──────────────────────────────────

def extract_metadata(metadata, operators_raw):
    user_participants = []

    # Operators từ compose (giống gốc)
    for key, item in metadata.get("compose", {}).get("operator", {}).items():
        operator = dict(item.get("user", {}))
        operator["role"] = "agent"
        user_participants.append({k: v for k, v in operator.items()
                                   if k in ("nickname", "user_id", "role") and v})

    # Customer
    meta = metadata.get("meta", {})
    device = meta.get("device") or {}
    geo = device.get("geolocation") or {}
    user = {"role": "user"}
    for k in ("nickname", "user_id", "email", "data"):
        v = meta.get(k) if k != "user_id" else metadata.get("people_id")
        if v:
            user[k] = v
    if geo.get("country"):
        user["country"] = geo["country"]
    user_participants.append(user)

    return {
        "session_id":        metadata.get("session_id", "unknown"),
        "website_id":        metadata.get("website_id", "unknown"),
        "state":             metadata.get("state"),
        "segments":          metadata.get("segments"),
        "created_at":        metadata.get("created_at"),
        "updated_at":        metadata.get("updated_at"),
        "user_participants": user_participants,
    }


def extract_messages(raw_msgs):
    result = []
    for item in raw_msgs:
        msg = {}
        for k in ("type", "from", "content", "timestamp", "read"):
            v = item.get(k)
            if v not in (None, "", [], {}):
                msg[k] = v
        u = item.get("user") or {}
        if u:
            msg["user"] = {k: v for k, v in u.items() if k in ("nickname", "user_id") and v}
        if msg:
            result.append(msg)
    return result


# ── Crawl ─────────────────────────────────────────────────────────────────────

def crawl_date(website_id, date_str, operators_raw, do_summary=False):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ7)
    day_start    = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_start_ms = int(day_start.timestamp() * 1000)
    day_end_ms   = day_start_ms + 86_400_000

    print(f"  📋 {date_str} — fetching conversations...")
    raw_conversations = fetch_conversations_for_day(website_id, day_start_ms, day_end_ms)
    print(f"  ✅ {len(raw_conversations)} conversations")

    results = []
    for i, metadata in enumerate(raw_conversations, 1):
        session_id = metadata.get("session_id", "unknown")
        print(f"    [{i}/{len(raw_conversations)}] {session_id}", end="", flush=True)

        # Extract metadata theo cách gốc
        conv = extract_metadata(metadata, operators_raw)
        conv["crawl_date"] = date_str
        conv["conv_uuid"]  = conv_uuid(session_id)

        # Fetch full messages (tất cả pages, tất cả types)
        raw_msgs = fetch_all_messages(website_id, session_id)
        messages = extract_messages(raw_msgs)

        # start_session / end_session từ messages (giống gốc)
        chat_msgs = [m for m in raw_msgs if m.get("type") not in ["event", "note"]]
        if chat_msgs:
            conv["start_session"] = datetime.fromtimestamp(
                chat_msgs[0].get("timestamp", 0) / 1000, tz=TZ7
            ).strftime("%Y-%m-%d %H:%M:%S")
            conv["end_session"] = datetime.fromtimestamp(
                chat_msgs[-1].get("timestamp", 0) / 1000, tz=TZ7
            ).strftime("%Y-%m-%d %H:%M:%S")

        # Chia messages thành segments, bỏ qua segment ≤ 4 tin nhắn
        raw_segments = split_segments(raw_msgs)
        conv["segments"] = []
        seg_idx = 0
        for seg_raw in raw_segments:
            seg_msgs = extract_messages(seg_raw)
            chat_only_msgs = [m for m in seg_msgs if m.get("type") not in ("event", "note", "animation")]
            if len(chat_only_msgs) <= 4:
                continue
            seg_idx += 1
            ts_list = [m.get("timestamp") for m in seg_raw if m.get("timestamp")]
            seg = {
                "segment":   seg_idx,
                "msg_count": len(seg_msgs),
                "messages":  seg_msgs,
            }
            if ts_list:
                seg["start"] = datetime.fromtimestamp(min(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S")
                seg["end"]   = datetime.fromtimestamp(max(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S")
            conv["segments"].append(seg)

        if not conv["segments"]:
            print(f"  — skipped (no valid segments)", flush=True)
            continue

        conv["msg_count"]     = len(messages)
        conv["segment_count"] = len(conv["segments"])

        if do_summary:
            summaries = summarize_conversation(messages)
            if summaries:
                # Gắn summary + tags vào từng segment tương ứng
                for seg_summary in summaries:
                    idx = seg_summary["segment"] - 1
                    if idx < len(conv["segments"]):
                        conv["segments"][idx]["tags"]    = seg_summary.get("tags", [])
                        conv["segments"][idx]["summary"] = seg_summary.get("summary", "")

        print(f"  — {len(messages)} msgs", flush=True)
        results.append(conv)
        time.sleep(0.3)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",    help="Single date YYYY-MM-DD (default today)")
    parser.add_argument("--from",    dest="date_from", help="Start date YYYY-MM-DD")
    parser.add_argument("--to",      dest="date_to",   help="End date YYYY-MM-DD")
    parser.add_argument("--all",     action="store_true", help="Fetch all dates from website creation to today")
    parser.add_argument("--website", help="Specific website_id (default: all)")
    parser.add_argument("--summary", action="store_true", help="Generate AI summary for each conversation")
    args = parser.parse_args()

    if not IDENTIFIER or not KEY:
        print("❌ Missing CRISP_IDENTIFIER or CRISP_KEY in .env")
        return

    # Fetch websites một lần duy nhất
    _sites_cache = None
    def get_sites():
        nonlocal _sites_cache
        if _sites_cache is None:
            _sites_cache = fetch_websites()
        return _sites_cache

    # Websites
    if args.website:
        website_ids = [args.website]
    else:
        website_ids = [str(s["website_id"]) for s in get_sites()]
        if not website_ids:
            print("❌ No websites found. Try --website <id>.")
            return
        print(f"🌐 {len(website_ids)} website(s): {', '.join(website_ids)}")

    # Date range
    if args.all:
        earliest = None
        for s in get_sites():
            c = s.get("created_at")
            if c and (earliest is None or c < earliest):
                earliest = c
        if earliest:
            d_from = datetime.fromtimestamp(earliest / 1000, tz=TZ7).replace(tzinfo=None)
        else:
            d_from = datetime(2025, 8, 25)  # ngày bắt đầu dữ liệu thực tế
        d_to = datetime.now(TZ7).replace(tzinfo=None)
        dates = [(d_from + timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range((d_to - d_from).days + 1)]
        print(f"📅 --all: {dates[0]} → {dates[-1]} ({len(dates)} ngày)")
    elif args.date_from and args.date_to:
        d_from = datetime.strptime(args.date_from, "%Y-%m-%d")
        d_to   = datetime.strptime(args.date_to,   "%Y-%m-%d")
        dates  = [(d_from + timedelta(days=i)).strftime("%Y-%m-%d")
                  for i in range((d_to - d_from).days + 1)]
    else:
        dates = [args.date or datetime.now(TZ7).strftime("%Y-%m-%d")]

    all_results = []
    for website_id in website_ids:
        print(f"\n🌐 Website: {website_id}")
        operators_raw = fetch_operators(website_id)
        print(f"  👥 {len(operators_raw)} operators")

        for date_str in dates:
            day_results = crawl_date(website_id, date_str, operators_raw, do_summary=args.summary)
            all_results.extend(day_results)

    if not all_results:
        print("⚠️  No conversations collected.")
        return

    tag = (dates[0].replace("-", "") if len(dates) == 1
           else f"{dates[0].replace('-','')}_{dates[-1].replace('-','')}")

    def _strip_messages(conv):
        """Bỏ messages khỏi từng segment, giữ lại summary + tags."""
        c = {k: v for k, v in conv.items() if k != "segments"}
        c["segments"] = [{k: v for k, v in s.items() if k != "messages"}
                         for s in conv.get("segments", [])]
        return c

    def _strip_summary(conv):
        """Bỏ summary + tags khỏi từng segment, giữ lại messages."""
        c = {k: v for k, v in conv.items() if k != "segments"}
        c["segments"] = [{k: v for k, v in s.items() if k not in ("summary", "tags")}
                         for s in conv.get("segments", [])]
        return c

    # File 1: chỉ chat (không có summary/tags)
    chat_only = [_strip_summary(r) for r in all_results]

    # File 2: chỉ summary (metadata + segments với summary/tags, không có messages)
    has_summary = any(
        any("summary" in s for s in r.get("segments", []))
        for r in all_results
    )
    summary_only = [_strip_messages(r) for r in all_results] if has_summary else []

    # File 3: full (cả chat lẫn summary)
    full = all_results

    def save(data, suffix):
        path = f"crawl_{tag}{suffix}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size = os.path.getsize(path) / 1024 / 1024
        print(f"  💾 {path}  ({len(data)} convs, {size:.1f} MB)")
        return path

    print()
    save(chat_only,    "_chat")
    if summary_only:
        save(summary_only, "_summary")
    save(full,         "_full")

    total_msgs = sum(r.get("msg_count", 0) for r in all_results)
    print(f"\n✅ {len(all_results)} conversations, {total_msgs} messages tổng cộng")


if __name__ == "__main__":
    main()
