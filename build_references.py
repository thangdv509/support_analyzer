"""
Build qa_references.json from scored QA CSV files.

This script:
1. Parses both QA CSV files (Mar + Apr 2026)
2. Selects representative examples (perfect + deducted, diverse criteria)
3. Fetches their transcripts from Crisp API
4. Builds expected grading JSON from CSV scores
5. Saves to qa_references.json

Run once: python3 build_references.py
The output file is then loaded by analyzer_v2.py for few-shot prompting.
"""

import os
import csv
import json
import re
import time
from datetime import datetime, timezone, timedelta
from crisp_api import Crisp
from dotenv import load_dotenv

load_dotenv()

IDENTIFIER = os.getenv("CRISP_IDENTIFIER")
KEY = os.getenv("CRISP_KEY")

# All website IDs seen in the CSVs
WEBSITE_ID = "17e47fa7-bddf-4074-b627-df66a29a740e"

KEY_MAP = [
    "greetings", "grammar", "communication", "listening", "tone_pace", "empathy",
    "enthusiastic", "probing", "solution", "proactiveness", "transferring",
    "resources", "extra_mile", "review_asking"
]
MAX_SCORES = {
    "greetings": 0.25, "grammar": 1.25, "communication": 2.0, "listening": 1.5,
    "tone_pace": 0.75, "empathy": 0.75, "enthusiastic": 1.5, "probing": 1.5,
    "solution": 3.0, "proactiveness": 2.0, "transferring": 2.0, "resources": 0.5,
    "extra_mile": 1.5, "review_asking": 1.5
}

# Short template justifications for deductions (used when CSV has no comment)
DEDUCTION_REASONS = {
    "greetings": "Thiếu tên agent hoặc tên brand trong lời chào.",
    "grammar": "Có câu sai nghĩa hoặc gây hiểu nhầm cho khách.",
    "communication": "Câu trả lời không rõ ràng, lan man hoặc gây confused cho khách.",
    "listening": "Bỏ qua một hoặc nhiều câu hỏi mà khách đặt ra.",
    "tone_pace": "Cộc lốc, thiếu lịch sự hoặc để khách chờ lâu không cập nhật.",
    "empathy": "Khách bức xúc/lo lắng rõ ràng nhưng không có câu nào thể hiện quan tâm.",
    "enthusiastic": "Support thụ động, cầm chừng, né tránh xử lý vấn đề rõ ràng.",
    "probing": "Vấn đề chưa rõ nhưng không hỏi thêm, dẫn đến xử lý sai hướng.",
    "solution": "Agent hướng dẫn sai hoặc bỏ qua vấn đề chính của khách.",
    "proactiveness": "Vấn đề chính đã xong nhưng bỏ hẳn cơ hội giúp thêm rõ ràng.",
    "transferring": "Vấn đề cần dev/kỹ thuật nhưng không chuyển case hoặc không xác nhận với team.",
    "resources": "Có cơ hội rõ ràng chia sẻ docs/link hữu ích nhưng không làm.",
    "extra_mile": "Bỏ qua cơ hội gợi ý tính năng/plan rõ ràng có lợi cho khách.",
    "review_asking": "Khách khen ngợi nhiệt tình rõ ràng nhưng support bỏ qua không xin review."
}


def parse_csvs(files):
    """Parse QA CSV files, return list of structured entries."""
    entries = []
    for filename in files:
        if not os.path.exists(filename):
            print(f"⚠️  File not found: {filename}")
            continue
        with open(filename, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        for row in rows[1:]:
            if len(row) < 20:
                continue
            try:
                url = row[2].strip()
                if not url.startswith("https://app.crisp.chat"):
                    continue
                rating = float(row[5])
                if rating == 0:
                    continue
                agent = row[4].strip()
                app = row[3].strip()
                date = row[1].strip()

                scores = {}
                deductions = {}
                for i, key in enumerate(KEY_MAP):
                    try:
                        score = float(row[6 + i])
                        scores[key] = score
                        if score < MAX_SCORES[key]:
                            deductions[key] = {
                                "got": score,
                                "max": MAX_SCORES[key],
                                "lost": round(MAX_SCORES[key] - score, 3)
                            }
                    except Exception:
                        scores[key] = MAX_SCORES[key]

                # Extract session_id from URL (keep session_ prefix as Crisp API uses it)
                m = re.search(r"/inbox/(session_[\w-]+)", url)
                sid = m.group(1) if m else ""
                wid_m = re.search(r"/website/([\w-]+)/", url)
                wid = wid_m.group(1) if wid_m else WEBSITE_ID

                if sid:
                    entries.append({
                        "date": date, "url": url, "app": app, "agent": agent,
                        "rating": rating, "scores": scores, "deductions": deductions,
                        "session_id": sid, "website_id": wid
                    })
            except Exception:
                pass
    return entries


def select_examples(entries):
    """
    Select diverse examples for few-shot prompting:
    - 1 perfect (10.0) — baseline
    - 1 with solution deduction only (clear wrong answer)
    - 1 with solution=0 or very low (worst case)
    - 1 with transferring=0 (completely missed case transfer)
    - 1 with review_asking deduction only (common, subtle)
    - 1 with communication deduction (clarity issue)
    Returns list of entries.
    """
    selected = []
    used_sessions = set()

    def pick(filter_fn, label):
        for e in entries:
            if e["session_id"] not in used_sessions and filter_fn(e):
                selected.append({**e, "_label": label})
                used_sessions.add(e["session_id"])
                return True
        return False

    # 1. Perfect example
    pick(lambda e: e["rating"] == 10.0 and not e["deductions"], "perfect_10")

    # 2. solution deducted only (solution < 3, nothing else deducted)
    pick(lambda e: "solution" in e["deductions"] and len(e["deductions"]) == 1
         and e["deductions"]["solution"]["got"] <= 1.5, "solution_deducted")

    # 3. solution=0 or major solution deduction
    pick(lambda e: "solution" in e["deductions"]
         and e["deductions"]["solution"]["got"] == 0
         and e["session_id"] not in used_sessions, "solution_zero")

    # 4. transferring deducted (0 = complete failure)
    pick(lambda e: "transferring" in e["deductions"]
         and e["deductions"]["transferring"]["got"] == 0, "transferring_zero")

    # 5. review_asking deducted only
    pick(lambda e: set(e["deductions"].keys()) == {"review_asking"}, "review_only")

    # 6. communication deducted
    pick(lambda e: "communication" in e["deductions"]
         and e["deductions"]["communication"]["got"] <= 1.0, "communication_deducted")

    print(f"Selected {len(selected)} examples:")
    for s in selected:
        deductions_str = ", ".join([f"{k}({v['got']}/{v['max']})" for k, v in s["deductions"].items()])
        print(f"  [{s['_label']}] {s['rating']:.2f} | {s['agent']} | {s['app']} | {deductions_str or 'perfect'}")
        print(f"    {s['session_id']}")
    return selected


def fetch_transcript(client, website_id, session_id, target_agent):
    """
    Fetch messages for a session and return formatted transcript string.
    Filters to the segment handled by target_agent (matched by first name, case-insensitive).
    Returns None on failure.
    """
    all_messages = []
    last_timestamp = None

    # Get operator map for name resolution
    op_map = {}
    try:
        operators = client.website.list_website_operators(website_id)
        op_map = {
            str(op["details"]["user_id"]): (op["details"].get("first_name") or op["details"].get("email"))
            for op in operators if op and "details" in op
        }
    except Exception:
        pass

    # Get conversation meta for customer name + review
    meta = {}
    try:
        meta = client.website.get_conversation_metas(website_id, session_id) or {}
    except Exception:
        pass

    cust_name = str(meta.get("nickname") or "Customer")
    review_value = (meta.get("data") or {}).get("review_value")
    review_info = f" (Khách ĐÃ CHO REVIEW {review_value} sao)" if review_value else ""

    # Fetch all messages (paginated)
    for _ in range(15):
        query = {}
        if last_timestamp:
            query["timestamp_before"] = str(last_timestamp)
        try:
            msgs = client.website.get_messages_in_conversation(website_id, session_id, query)
            if not msgs:
                break
            all_messages.extend(msgs)
            msgs_sorted = sorted(msgs, key=lambda x: x.get("timestamp", 0))
            last_timestamp = msgs_sorted[0].get("timestamp")
            time.sleep(0.5)
            # Stop going back more than 120 days
            oldest_dt = datetime.fromtimestamp(last_timestamp / 1000, tz=timezone.utc)
            if (datetime.now(tz=timezone.utc) - oldest_dt).days > 120:
                break
        except Exception as e:
            if "rate_limited" in str(e):
                print(f"    ⏳ Rate limited, sleeping 60s...")
                time.sleep(60)
                continue
            print(f"    ❌ Error fetching messages: {e}")
            break

    if not all_messages:
        return None

    all_messages.sort(key=lambda x: x.get("timestamp", 0))
    BOT_NAMES = {"pielab support", "pielab"}

    def get_op_name(m):
        u_info = m.get("user") or {}
        op_uid = str(u_info.get("user_id", ""))
        return str(u_info.get("nickname") or op_map.get(op_uid) or "Operator")

    def matches_agent(name, target):
        """Check if operator name matches target agent (first name, case-insensitive)."""
        name_lower = name.lower()
        target_lower = target.lower()
        # Match if first word of name == target, or name starts with target
        first_word = name_lower.split()[0] if name_lower else ""
        return first_word == target_lower or name_lower == target_lower

    # Find the segment where target_agent is the primary (last) operator
    # Strategy: split by resolved events, take last segment with target_agent
    def is_resolved_event(m):
        if m.get("type") != "event":
            return False
        c = m.get("content", "")
        if isinstance(c, dict):
            return (c.get("namespace") == "state:resolved" or c.get("type") == "resolved"
                    or c.get("action") == "resolved" or c.get("state") == "resolved")
        return str(c) == "resolved"

    segments = []
    current_seg = []
    for m in all_messages:
        current_seg.append(m)
        if is_resolved_event(m):
            segments.append(current_seg)
            current_seg = []
    if current_seg:
        segments.append(current_seg)

    # Find the last segment where target_agent appears as an operator
    target_segment = None
    for seg in reversed(segments):
        seg_agent_names = set()
        for m in seg:
            if m.get("from") == "operator" and m.get("type") not in ["event", "note"]:
                name = get_op_name(m)
                if name.lower() not in BOT_NAMES:
                    seg_agent_names.add(name)
        # Check if target_agent matches any operator in this segment
        for name in seg_agent_names:
            if matches_agent(name, target_agent):
                target_segment = seg
                break
        if target_segment:
            break

    # Fall back to all messages if no segment found
    if not target_segment:
        print(f"    ⚠️  Could not find segment for agent '{target_agent}', using all messages")
        target_segment = all_messages

    # Format transcript from target segment
    filtered = []
    last_op_msg = None
    app_name = "Unknown"
    found_agent_name = target_agent  # will be overwritten with actual name

    for m in target_segment:
        if m.get("type") in ["note", "event"]:
            continue
        is_op = m.get("from") == "operator"
        content = m.get("content", "")

        if is_op:
            name = get_op_name(m)
            if name.lower() in BOT_NAMES:
                continue
            # Only include target agent's messages (skip other operators)
            if not matches_agent(name, target_agent):
                continue
            found_agent_name = name
            last_op_msg = m
            if "DECO" in str(content).upper():
                app_name = "DECO"
            elif "SEARCHPIE" in str(content).upper() or "SEARCH PIE" in str(content).upper():
                app_name = "SearchPie"
            label = name
        else:
            label = cust_name
            last_op_msg = None

        if m.get("type") == "file" and isinstance(content, dict):
            content = f"[File: {content.get('name', 'unnamed')} - {content.get('url', '')}]"
        elif isinstance(content, dict):
            content = content.get("text") or str(content)

        filtered.append({"sender": label, "content": str(content), "is_op": is_op})

    if len(filtered) < 2:
        return None

    customer_seen_no_reply = (
        last_op_msg is not None and last_op_msg.get("read") == "chat"
    )
    seen_note = (
        " | ⚠️ KHÁCH ĐÃ SEEN tin nhắn cuối của support nhưng CHƯA REPLY — đây là lý do chưa kết thúc, không trừ điểm support vì điều này."
        if customer_seen_no_reply else ""
    )
    supp_info = f"{review_info}{seen_note}" if (review_info or seen_note) else "Chưa thấy có thông tin review từ hệ thống"

    transcript = f"--- THÔNG TIN BỔ SUNG: {supp_info} ---\n\n"
    transcript += f"[Agent được chấm: {found_agent_name}]\n\n"
    for f in filtered:
        prefix = f"  {f['sender']}: " if f["is_op"] else f"{f['sender']}: "
        transcript += f"{prefix}{str(f['content']).replace(chr(10), chr(10) + '      ')}\n\n"

    return transcript


def build_expected_grading(entry):
    """
    Build the expected grading JSON output from CSV scores.
    Uses brief template justifications.
    """
    criteria = {}
    for key in KEY_MAP:
        score = entry["scores"].get(key, MAX_SCORES[key])
        if key in entry["deductions"]:
            justification = DEDUCTION_REASONS.get(key, "Không đáp ứng tiêu chí.")
        else:
            justification = "Đáp ứng tốt tiêu chí này."
        criteria[key] = {"score": score, "justification": justification}

    total = round(sum(entry["scores"].get(k, MAX_SCORES[k]) for k in KEY_MAP) / 2, 2)
    deduction_summary = ""
    if entry["deductions"]:
        parts = []
        for k, v in entry["deductions"].items():
            parts.append(f"{k} ({v['got']}/{v['max']})")
        deduction_summary = f"Điểm {total}/10. Trừ điểm: {', '.join(parts)}."
    else:
        deduction_summary = f"Điểm {total}/10. Chat đạt tiêu chuẩn tốt, không có lỗi đáng kể."

    return {"criteria": criteria, "overall_summary": deduction_summary}


def main():
    csv_files = [
        "[PieLab] 2026_QA Chat - Mar_2026.csv",
        "[PieLab] 2026_QA Chat - April_2026.csv"
    ]

    print("📂 Parsing CSV files...")
    entries = parse_csvs(csv_files)
    print(f"  → {len(entries)} total scored chats loaded")

    examples = select_examples(entries)

    if not all([IDENTIFIER, KEY]):
        print("❌ Missing Crisp credentials in .env")
        return

    client = Crisp()
    client.set_tier("plugin")
    client.authenticate(IDENTIFIER, KEY)

    references = []
    for ex in examples:
        sid = ex["session_id"]
        wid = ex["website_id"]
        print(f"\n🔍 Fetching transcript: {sid} ({ex['agent']}, {ex['app']}, rating={ex['rating']})...")
        time.sleep(1)
        transcript = fetch_transcript(client, wid, sid, ex["agent"])
        if not transcript:
            print(f"  ⚠️  Could not fetch transcript, skipping.")
            continue
        msg_count = transcript.count("\n\n") - 2
        print(f"  ✅ Got transcript ({msg_count} messages)")

        expected_output = build_expected_grading(ex)

        references.append({
            "session_id": sid,
            "website_id": wid,
            "agent": ex["agent"],
            "app": ex["app"],
            "date": ex["date"],
            "rating": ex["rating"],
            "deductions": ex["deductions"],
            "label": ex.get("_label", ""),
            "transcript": transcript,
            "expected_output": expected_output
        })

    output_path = "qa_references.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(references, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Saved {len(references)} reference examples to {output_path}")
    print("\nSummary:")
    for r in references:
        deductions = ", ".join([f"{k}({v['got']}/{v['max']})" for k, v in r["deductions"].items()]) or "perfect"
        print(f"  [{r['label']}] {r['rating']:.2f} | {r['agent']} | {r['app']} | {deductions}")


if __name__ == "__main__":
    main()
