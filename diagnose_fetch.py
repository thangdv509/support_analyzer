"""
Diagnostic: phân tích chi tiết từng bước drop khi fetch chat cho một ngày.
Không chấm điểm, chỉ đếm và phân loại.
"""
import os, time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from crisp_api import Crisp

load_dotenv()

IDENTIFIER = os.getenv("CRISP_IDENTIFIER")
KEY        = os.getenv("CRISP_KEY")
BOT_NAMES  = {"pielab support", "pielab"}

def diagnose_date(target_date_str: str):
    client = Crisp(); client.set_tier("plugin")
    client.authenticate(IDENTIFIER, KEY)

    TZ7 = timezone(timedelta(hours=7))
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").replace(tzinfo=TZ7)
    day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end   = day_start + timedelta(days=1)
    day_start_ts = int(day_start.timestamp() * 1000)

    sites = client.plugin.list_all_connect_websites(1, False)
    website_id = str(sites[0]['website_id'])
    op_map = {}
    try:
        operators = client.website.list_website_operators(website_id)
        op_map = {str(op['details']['user_id']): (op['details'].get('first_name') or op['details'].get('email'))
                  for op in operators if op and 'details' in op}
    except: pass

    # ── Step 1: count what Crisp returns before any filter ──
    total_from_crisp  = 0
    skipped_too_new   = 0   # updated_at >= day_end (after target day)
    added_to_list     = 0

    conv_list = []; seen_sids = set()
    for resolved_filter in [False, True]:
        for page in range(1, 51):
            try:
                kwargs = {"filter_date_start": str(day_start_ts)}
                if resolved_filter: kwargs["filter_resolved"] = "true"
                conversations = client.website.search_conversations(website_id, page, **kwargs)
                if not conversations: break
            except Exception as e:
                if "rate_limited" in str(e): time.sleep(90); continue
                break

            passed_target = False
            for conv in conversations:
                sid = str(conv.get("session_id", ""))
                updated_at = datetime.fromtimestamp(conv.get("updated_at", 0) / 1000, tz=TZ7)

                if updated_at < day_start:
                    passed_target = True
                elif updated_at < day_end:
                    total_from_crisp += 1
                    if sid not in seen_sids:
                        seen_sids.add(sid); conv_list.append(conv); added_to_list += 1
                else:
                    # updated_at >= day_end → currently SKIPPED in production
                    skipped_too_new += 1
                    total_from_crisp += 1

            if passed_target: break

    print(f"\n{'='*55}")
    print(f"📅 {target_date_str}")
    print(f"  Crisp returned  : {total_from_crisp} convs (filtered by date_start)")
    print(f"  → added to list : {added_to_list}  (updated_at WITHIN target day)")
    print(f"  → skipped too new: {skipped_too_new}  (updated_at AFTER target day — BUG?)")

    # ── Step 2: per-conv drop analysis ──
    drop_no_msgs = drop_no_segment = drop_no_ops = drop_outreach = drop_too_short = 0
    graded = 0

    for conv in conv_list:
        time.sleep(0.4)
        sid = str(conv["session_id"])
        all_messages = []; last_timestamp = None; success = False

        for _retry in range(5):
            query = {}
            if last_timestamp: query["timestamp_before"] = str(last_timestamp)
            try:
                msgs = client.website.get_messages_in_conversation(website_id, sid, query)
                if not msgs: success = True; break
                all_messages.extend(msgs)
                msgs.sort(key=lambda x: x.get("timestamp", 0))
                last_timestamp = msgs[0].get("timestamp")
                m_time = datetime.fromtimestamp(last_timestamp / 1000, tz=TZ7)
                if m_time < day_start - timedelta(days=1): success = True; break
                time.sleep(0.3)
            except Exception as e:
                if "rate_limited" in str(e): time.sleep(90); continue
                break
        else:
            drop_no_msgs += 1; continue

        all_messages.sort(key=lambda x: x.get("timestamp", 0))

        # Segment split
        segments = []; cur = []
        for m in all_messages:
            cur.append(m)
            mc = m.get("content", "")
            if m.get("type") == "event" and (
                (isinstance(mc, dict) and (mc.get("namespace") == "state:resolved" or mc.get("type") == "resolved"))
                or str(mc) == "resolved"
            ):
                segments.append(cur); cur = []
        if cur: segments.append(cur)

        if not segments: drop_no_segment += 1; continue

        # Find segment with activity in target day
        valid_seg = None
        for seg in reversed(segments):
            if any(
                day_start <= datetime.fromtimestamp(m.get("timestamp",0)/1000, tz=TZ7) < day_end
                and m.get("type") not in ["event","note"]
                for m in seg if m.get("timestamp")
            ):
                valid_seg = seg; break

        if valid_seg is None: drop_no_segment += 1; continue

        # Check operators
        seg_ops = set()
        for m in valid_seg:
            if m.get("from") == "operator" and m.get("type") not in ["event","note"]:
                u = m.get("user") or {}
                name = str(u.get("nickname") or op_map.get(str(u.get("user_id",""))) or "Operator")
                if name.lower() not in BOT_NAMES: seg_ops.add(name)

        if not seg_ops: drop_no_ops += 1; continue

        # Build filtered messages
        filtered = []
        for m in valid_seg:
            if m.get("type") in ["note","event"]: continue
            is_op = m.get("from") == "operator"
            if is_op:
                u = m.get("user") or {}
                name = str(u.get("nickname") or op_map.get(str(u.get("user_id",""))) or "Operator")
                if name.lower() in BOT_NAMES: continue
            content = m.get("content","")
            if isinstance(content, dict): content = content.get("text") or str(content)
            filtered.append({"is_op": is_op, "content": str(content)})

        op_meaningful = [f for f in filtered if f["is_op"] and len(f["content"].strip()) > 3]
        if not op_meaningful: drop_too_short += 1; continue

        customer_msgs = [f for f in filtered if not f["is_op"]]
        if not customer_msgs: drop_outreach += 1; continue

        graded += 1

    print(f"  ── Drop breakdown (of {added_to_list} fetched) ──")
    print(f"  no_msgs    : {drop_no_msgs}")
    print(f"  no_segment : {drop_no_segment}")
    print(f"  no_ops     : {drop_no_ops}   (bot-only / no human agent)")
    print(f"  outreach   : {drop_outreach}  (agent messaged, customer never replied)")
    print(f"  too_short  : {drop_too_short}  (agent msgs all empty/very short)")
    print(f"  ✅ GRADED  : {graded}")
    print(f"  🚨 MISSING due to updated_at filter: {skipped_too_new}")
    return {"date": target_date_str, "crisp_total": total_from_crisp,
            "skipped_too_new": skipped_too_new, "graded": graded}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--from", dest="date_from")
    parser.add_argument("--to",   dest="date_to")
    args = parser.parse_args()

    if args.date_from and args.date_to:
        d = datetime.strptime(args.date_from, "%Y-%m-%d")
        end = datetime.strptime(args.date_to, "%Y-%m-%d")
        while d <= end:
            diagnose_date(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
    else:
        date = args.date or datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
        diagnose_date(date)
