import os
import json
import argparse
import requests
import traceback
import time
from datetime import datetime, timezone, timedelta
from crisp_api import Crisp
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

# --- Config ---
IDENTIFIER = os.getenv("CRISP_IDENTIFIER")
KEY = os.getenv("CRISP_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
# Model options (set OPENROUTER_MODEL in .env to override):
#   google/gemini-2.5-pro-preview   — default, fast & capable
#   anthropic/claude-opus-4-6       — best Claude, excellent for structured reasoning
#   openai/o4-mini                  — fast, cost-effective
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-001")

# --- Few-shot reference examples ---
QA_REFERENCES_PATH = os.path.join(os.path.dirname(__file__), "qa_references.json")
_FEW_SHOT_MESSAGES = []  # populated by load_few_shot_examples()

def load_few_shot_examples(max_examples=4, max_transcript_chars=6000):
    """
    Load qa_references.json và build few-shot message pairs.
    Mỗi label có pool nhiều examples — mỗi lần gọi random chọn 1 từ mỗi pool.
    """
    import random
    global _FEW_SHOT_MESSAGES
    if not os.path.exists(QA_REFERENCES_PATH):
        print(f"ℹ️  No qa_references.json found at {QA_REFERENCES_PATH}. Run build_references_from_db.py to generate it.")
        return

    with open(QA_REFERENCES_PATH, "r", encoding="utf-8") as f:
        refs = json.load(f)

    # Nhóm theo label
    priority_order = ["perfect_10", "solution_zero", "review_only", "transferring_zero",
                      "solution_deducted", "communication_deducted"]
    pools: dict[str, list] = {}
    for ref in refs:
        label = ref.get("label", "other")
        pools.setdefault(label, []).append(ref)

    # Random chọn 1 từ mỗi pool, theo priority order, tối đa max_examples
    chosen = []
    for label in priority_order:
        if label in pools and len(chosen) < max_examples:
            chosen.append(random.choice(pools[label]))

    messages = []
    for ref in chosen:
        transcript = ref["transcript"]
        if len(transcript) > max_transcript_chars:
            transcript = transcript[:max_transcript_chars] + "\n\n[... lược bớt phần còn lại ...]"
        messages.append({"role": "user",      "content": f"Chấm đoạn chat sau:\n\n{transcript}"})
        messages.append({"role": "assistant", "content": json.dumps(ref["expected_output"], ensure_ascii=False)})

    _FEW_SHOT_MESSAGES = messages
    print(f"✅ Loaded {len(chosen)} few-shot examples (labels: {[r.get('label') for r in chosen]})")

GRADING_CRITERIA = """
Bạn là QA Support chấm điểm hội thoại theo 14 tiêu chí. Tổng 20 điểm.

NGUYÊN TẮC CHUNG:
- Chỉ chấm agent được chỉ định. Nếu nhiều agent xuất hiện, bỏ qua lỗi của agent khác.
- Nếu THÔNG TIN BỔ SUNG ghi khách đã SEEN nhưng chưa reply → không trừ điểm vì chat chưa kết thúc.
- Nếu THÔNG TIN BỔ SUNG ghi khách đã cho review → đủ điểm mục Asking for Review.
- Tin nhắn tự động/trigger → không tính vào đánh giá.
- Đọc chat như một người, không phải máy quét lỗi: không soi từng dấu câu, ký tự, cách viết hoa. Typo nhỏ, sai dấu (`it;s`, `dont`, `Im`...), informal, viết tắt, emoji đều bỏ qua hoàn toàn. Chỉ trừ Grammar khi câu sai nghĩa khiến khách hiểu sai — phải trích dẫn câu đó và giải thích cụ thể tại sao gây nhầm.
- Tin nhắn khách lặp lại y nguyên nhiều lần (trigger/bot) → bỏ qua hoàn toàn, không dùng để đánh giá bất kỳ tiêu chí nào.
- Tiêu chí không có cơ hội xuất hiện → đủ điểm, ghi ngắn lý do.
- Chỉ trừ khi có bằng chứng rõ ràng trong chat, không suy diễn.
- Greetings KHÔNG yêu cầu "Hi" hay "Hello" — "It's Jane from DECO team here" là ĐỦ. Chỉ trừ khi không có tên hoặc không có brand, không phải vì thiếu lời chào xã giao.
- Resources KHÔNG được tự suy diễn ra "cơ hội chia sẻ docs" — phải có bằng chứng rõ ràng trong chat là khách cần tài liệu và agent bỏ qua. Agent đã trả lời xong bằng lời = đủ điểm, không cần share thêm link.
- Tin nhắn agent dạng re-engage/follow-up ("Hi, still here!", "Just checking in", "Let me know if you need help") khi khách không phản hồi = hành động CHỦ ĐỘNG tốt, KHÔNG phải bỏ qua câu hỏi. KHÔNG trừ Listening/Enthusiastic/Solution vì những tin này.
- Khi THÔNG TIN BỔ SUNG ghi khách đã cho review tốt (4-5 sao): đây là tín hiệu mạnh cho thấy khách hài lòng — không được chấm các tiêu chí giao tiếp quá nghiêm khắc khi mâu thuẫn với review này.

LƯU Ý: Chat outreach (khách chưa reply lần nào) đã được loại ra trước khi chấm — không có trong dataset này.

NGUYÊN TẮC CASE CHƯA XỬ LÝ XONG:
- Chat kết thúc mà vấn đề chưa giải quyết xong là BÌNH THƯỜNG — khách có thể offline giữa chừng, vấn đề cần dev fix, cần thêm thông tin. KHÔNG trừ điểm Solution/Pro-activeness/Transfer chỉ vì case chưa done.
- Support xin thêm video/screenshot/log để điều tra = Probing TỐT, không phải thất bại. Không trừ điểm.
- Khách không hợp lý, yêu cầu sai, vấn đề ngoài khả năng support → không trừ điểm agent. Lỗi của khách không phải lỗi của agent.
- Chỉ trừ Solution khi: agent hướng dẫn SAI rõ ràng, bỏ qua vấn đề hoàn toàn, hoặc cố tình không xử lý.

PHÂN BIỆT CHAT TỐT VÀ CHAT ĐẠT YÊU CẦU:
- 9–10 điểm: agent xử lý mượt, chủ động, giao tiếp tốt, không có lỗi đáng kể.
- 7–8 điểm: có 1–2 điểm cần cải thiện rõ ràng nhưng không ảnh hưởng kết quả.
- Dưới 7: có lỗi nghiêm trọng hoặc nhiều lỗi nhỏ tích lũy.
- CẢNH BÁO: Nếu hầu hết chat cho điểm 10/10, khả năng cao đang chấm quá lỏng. Phải phân biệt được chat thực sự xuất sắc với chat chỉ đạt yêu cầu tối thiểu.

CÁCH VIẾT JUSTIFICATION:
Tiếng Việt, tự nhiên như nhận xét team lead — không dùng "tiêu chí", "theo quy tắc", "điểm số".
- Đủ điểm: khen ngắn điều làm tốt.
- Trừ điểm: (1) vấn đề cụ thể + trích dẫn, (2) ảnh hưởng thực tế, (3) ví dụ câu viết lại (CÙNG ngôn ngữ gốc của chat), (4) gợi ý cải thiện.

THANG ĐIỂM THỰC TẾ:
- Grammar, Tone/Pace, Empathy, Enthusiastic: hiếm khi trừ — chỉ khi lỗi nghiêm trọng rõ ràng.
- Solution khi trừ: lỗi nhẹ/chưa hoàn chỉnh → 2.0–2.5/3.0; sai hướng rõ → 1.0–1.5/3.0.
- Case Transfer khi trừ: gần như luôn là 0.5/2.0.
- Ask Review khi trừ: luôn là 1.0/1.5 — không bao giờ cho 0.

ASKING FOR REVIEW (1.5đ):
- Khách đã cho review, hoặc support có xin bất kỳ lúc nào → đủ điểm.
- Chat chưa kết thúc, khách SEEN chưa reply, khách bực bội, vấn đề đang xử lý → đủ điểm.
- Chat kết thúc bình thường không xin → đủ điểm (không bắt buộc).
- CHỈ cho 1.0/1.5 khi: khách khen ngợi rất nhiệt tình rõ ràng mà support bỏ qua hoàn toàn.

TIÊU CHÍ (tổng 20đ):
1.  Greetings & Branding (0.25): Có tên người VÀ tên brand dưới bất kỳ hình thức — không cần phải có "Hi/Hello" trước. "It's Jane from DECO team" là ĐỦ điểm. Trừ hết 0.25 chỉ khi thiếu hẳn tên hoặc brand. Khách vào thẳng kỹ thuật = đủ điểm.
2.  Grammar & Vocabulary (1.25): Chỉ trừ khi câu sai nghĩa hoặc gây hiểu nhầm thực sự. Dẫn chứng cụ thể bắt buộc.
3.  Clear & Concise (2.0): Trừ khi lạc đề, lặp vô nghĩa, hoặc giải thích rối gây confusion. Mức trừ: 0.25–1.0.
4.  Active Listening (1.5): Trừ khi bỏ sót câu hỏi khách đặt ra — nêu đúng câu bị bỏ qua.
5.  Tone & Pace (0.75): Trừ khi cộc lốc, thiếu lịch sự rõ ràng, hoặc để khách chờ lâu không cập nhật.
6.  Empathy (0.75): Trừ khi khách bức xúc/lo lắng rõ ràng mà không một câu nào thể hiện quan tâm. Chat bình thường = đủ điểm.
7.  Enthusiastic (1.5): Mặc định đủ điểm. CHỈ trừ khi agent né tránh, từ chối hỗ trợ, hoặc thái độ rõ ràng không muốn giúp — không trừ chỉ vì chat ngắn, chưa có cơ hội thể hiện, hay phong cách giao tiếp tự nhiên bình thường.
8.  Probing (1.5): Mặc định đủ điểm. CHỈ trừ khi vấn đề mơ hồ rõ ràng mà agent xử lý luôn sai hướng vì không hỏi thêm. Vấn đề đã rõ = đủ điểm. Xin video/screenshot/log = probing TỐT. KHÔNG trừ khi chat còn ngắn hoặc agent đang trong bước xử lý.
9.  Correct Solution (3.0): Mặc định đủ điểm. CHỈ trừ khi agent hướng dẫn SAI rõ ràng hoặc bỏ qua vấn đề hoàn toàn. Case chưa done vì khách offline/cần thêm thời gian/cần dev = BÌNH THƯỜNG, không trừ. Lỗi nhẹ: 2.0–2.5; sai hướng rõ: 1.0–1.5.
10. Pro-activeness (2.0): Mặc định đủ điểm. CHỈ trừ khi vấn đề chính đã xong hoàn toàn mà bỏ hẳn cơ hội giúp thêm rõ ràng — không trừ nếu chat còn đang dở, chưa resolve, hoặc không có cơ hội hiện ra.
11. Case Transferring (2.0): Mặc định đủ điểm. CHỈ trừ khi vấn đề rõ ràng cần dev/kỹ thuật mà agent không đề cập gì đến việc chuyển/check với team. "Check with dev/team", "inform our technical team", "pass to team" = ĐỦ điểm. Không cần transfer = đủ điểm.
12. Resources Utilization (0.5): Trừ khi có cơ hội RÕ RÀNG chia sẻ docs/link mà không làm — nghĩa là vấn đề khách hỏi có docs cụ thể liên quan trực tiếp, và agent bỏ qua hoàn toàn. KHÔNG trừ khi: agent đã giải quyết xong bằng lời, vấn đề không có docs rõ ràng, hoặc chỉ là "có thể share thêm". Không được suy diễn cơ hội — phải thấy rõ trong chat.
13. Extra Mile (1.5): Mặc định đủ điểm. Trừ nhẹ khi bỏ qua cơ hội gợi ý tính năng/plan rõ ràng có lợi cho khách.
14. Asking for Review (1.5): Xem ASKING FOR REVIEW ở trên.

TRẢ VỀ JSON:
{
  "criteria": {
    "greetings": {"score": ..., "justification": "..."},
    "grammar": {"score": ..., "justification": "..."},
    "communication": {"score": ..., "justification": "..."},
    "listening": {"score": ..., "justification": "..."},
    "tone_pace": {"score": ..., "justification": "..."},
    "empathy": {"score": ..., "justification": "..."},
    "enthusiastic": {"score": ..., "justification": "..."},
    "probing": {"score": ..., "justification": "..."},
    "solution": {"score": ..., "justification": "..."},
    "proactiveness": {"score": ..., "justification": "..."},
    "transferring": {"score": ..., "justification": "..."},
    "resources": {"score": ..., "justification": "..."},
    "extra_mile": {"score": ..., "justification": "..."},
    "review_asking": {"score": ..., "justification": "..."}
  },
  "overall_summary": "..."
}
"""

def fetch_chats(target_date_str):
    if not all([IDENTIFIER, KEY]):
        print("❌ Missing Crisp credentials.")
        return []

    client = Crisp()
    client.set_tier("plugin")
    client.authenticate(IDENTIFIER, KEY)

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=7)))
        day_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        
        day_start_ts = int(day_start.timestamp() * 1000)

        print(f"🔍 Fetching active chats for date: {target_date_str}")
        
        sites = None
        for _ in range(3):
            try:
                sites = client.plugin.list_all_connect_websites(1, False)
                break
            except Exception as e:
                if "rate_limited" in str(e):
                    print("⏳ Rate limited (init), sleeping 60s...")
                    time.sleep(60)
                else: raise e
        
        if not sites: return []
        
        all_valid_chats = []
        for site_idx, site in enumerate(sites):
            website_id = str(site['website_id'])
            site_name = site.get('name', 'Unknown Site')
            print(f"🌐 Processing Site {site_idx + 1}/{len(sites)}: {site_name} ({website_id})")
            
            op_map = {}
            for _ in range(3):
                try:
                    operators = client.website.list_website_operators(website_id)
                    op_map = {str(op['details']['user_id']): (op['details'].get('first_name') or op['details'].get('email')) for op in operators if op and 'details' in op}
                    print(f"  ✅ Fetched {len(op_map)} operators for {site_name}")
                    break
                except Exception as e:
                    if "rate_limited" in str(e):
                        print(f"⏳ Rate limited (ops) for {site_name}, sleeping 60s...")
                        time.sleep(60)
                    else:
                        print(f"⚠️ Cannot fetch operators for {site_name}, will use UUID + nickname detection.")
                        break


            # Fetch cả resolved và unresolved, dedup theo session_id
            # Crisp trả về newest-first, dùng filter_date_start=target_day và scan đến khi tìm đủ
            conv_list = []; seen_sids = set()
            for resolved_filter in [False, True]:
                for conv_page in range(1, 51):  # tối đa 50 pages (~1000 conv) cho ngày xa trong quá khứ
                    try:
                        kwargs = {"filter_date_start": str(day_start_ts)}
                        if resolved_filter:
                            kwargs["filter_resolved"] = "true"
                        conversations = client.website.search_conversations(website_id, conv_page, **kwargs)
                        if not conversations: break
                    except Exception as e:
                        if "rate_limited" in str(e):
                            print(f"⏳ Rate limited on page {conv_page}, sleeping 90s...")
                            time.sleep(90)
                            continue
                        elif "token_scope_forbidden" in str(e):
                            print(f"⛔ Token thiếu scope cho {site_name}. Bỏ qua.")
                            break
                        else: raise e
                    passed_target = False
                    for conv in conversations:
                        sid = str(conv.get("session_id", ""))
                        updated_at_ts_conv = conv.get("updated_at", 0)
                        updated_at = datetime.fromtimestamp(updated_at_ts_conv / 1000, tz=timezone(timedelta(hours=7)))
                        if updated_at < day_start:
                            passed_target = True  # đã qua ngày target, conv còn lại cũ hơn
                        elif updated_at < day_end:
                            if sid not in seen_sids:
                                seen_sids.add(sid)
                                conv_list.append(conv)
                    if passed_target: break  # không cần scan thêm page
            print(f"  📋 Found {len(conv_list)} conversations to process for {site_name}")

            drop_no_msgs = 0; drop_no_segment = 0; drop_no_ops = 0; drop_too_short = 0
            for conv in conv_list:
                    time.sleep(0.5)
                    conv_is_resolved = conv.get("state") == "resolved"
                    sid = str(conv["session_id"])
                    all_messages = []
                    last_timestamp = None
                    
                    success = False
                    for _retry in range(5):
                        query = {}
                        if last_timestamp: query["timestamp_before"] = str(last_timestamp)
                        try:
                            msgs = client.website.get_messages_in_conversation(website_id, sid, query)
                            if not msgs: 
                                success = True
                                break
                            all_messages.extend(msgs)
                            msgs.sort(key=lambda x: x.get("timestamp", 0))
                            last_timestamp = msgs[0].get("timestamp")
                            m_time = datetime.fromtimestamp(last_timestamp / 1000, tz=timezone(timedelta(hours=7)))
                            
                            if m_time < day_start - timedelta(days=1): 
                                success = True
                                break
                            time.sleep(0.5)
                        except Exception as e:
                            if "rate_limited" in str(e):
                                wait_time = 60 + (_retry * 30)
                                print(f"⏳ Rate limited on msgs {sid}, sleeping {wait_time}s...")
                                time.sleep(wait_time)
                                continue
                            break
                    else:
                        drop_no_msgs += 1; continue

                    all_messages.sort(key=lambda x: x.get("timestamp", 0))
                    
                    # Split into segments by resolved event, track resolved status
                    # Split into segments by resolved event
                    segments = []; current_segment = []
                    for m in all_messages:
                        current_segment.append(m)
                        m_type = m.get("type")
                        m_content = m.get("content")
                        is_res = False
                        if m_type == "event":
                            if isinstance(m_content, dict):
                                if m_content.get("namespace") == "state:resolved" or m_content.get("type") == "resolved" or m_content.get("action") == "resolved" or m_content.get("state") == "resolved":
                                    is_res = True
                            elif str(m_content) == "resolved": is_res = True
                        if is_res:
                            segments.append(current_segment); current_segment = []
                    if current_segment: segments.append(current_segment)

                    # Lấy segment CUỐI CÙNG chưa resolved (last segment không kết thúc bằng resolved event)
                    # Theo logic crawl.py: segment cuối = segments[-1], chỉ chưa resolved nếu
                    # nó không kết thúc bằng resolved event (tức là còn dở)
                    def _is_resolved_event(m):
                        if m.get("type") != "event": return False
                        c = m.get("content", "")
                        if isinstance(c, dict):
                            return (c.get("namespace") == "state:resolved" or
                                    c.get("type") == "resolved" or
                                    c.get("action") == "resolved" or
                                    c.get("state") == "resolved")
                        return str(c) == "resolved"

                    if not segments:
                        drop_no_segment += 1; continue

                    # Tìm segment cuối có activity trong ngày target
                    # (kể cả segment đã resolved — chat xong trong ngày vẫn phải chấm)
                    valid_seg = None
                    for seg in reversed(segments):
                        if any(
                            day_start <= datetime.fromtimestamp(m.get("timestamp", 0) / 1000, tz=timezone(timedelta(hours=7))) < day_end
                            and m.get("type") not in ["event", "note"]
                            for m in seg if m.get("timestamp")
                        ):
                            valid_seg = seg
                            break
                    if valid_seg is None:
                        drop_no_segment += 1; continue

                    last_seg = valid_seg

                    # Kiểm tra đúng 1 agent (không kể bot) đảm nhiệm segment này
                    BOT_NAMES = {"pielab support", "pielab"}
                    seg_operators = set()
                    for m in last_seg:
                        if m.get("from") == "operator" and m.get("type") not in ["event", "note"]:
                            u_info = m.get("user") or {}
                            op_uid = str(u_info.get("user_id", ""))
                            name = str(u_info.get("nickname") or op_map.get(op_uid) or "Operator")
                            if name.lower() not in BOT_NAMES:
                                seg_operators.add(name)
                    if len(seg_operators) == 0:
                        drop_no_ops += 1; continue  # không có agent nào

                    if len(seg_operators) == 1:
                        sole_agent = next(iter(seg_operators))
                    else:
                        # Nhiều agent: lấy agent có activity nhiều nhất trong ngày target
                        agent_msg_count: dict[str, int] = {}
                        for m in last_seg:
                            if m.get("from") != "operator" or m.get("type") in ["event", "note"]: continue
                            m_dt = datetime.fromtimestamp(m.get("timestamp", 0) / 1000, tz=timezone(timedelta(hours=7)))
                            if not (day_start <= m_dt < day_end): continue
                            u_info = m.get("user") or {}
                            op_uid = str(u_info.get("user_id", ""))
                            name = str(u_info.get("nickname") or op_map.get(op_uid) or "Operator")
                            if name.lower() not in BOT_NAMES:
                                agent_msg_count[name] = agent_msg_count.get(name, 0) + 1
                        if not agent_msg_count:
                            drop_no_ops += 1; continue
                        sole_agent = max(agent_msg_count, key=lambda k: agent_msg_count[k])
                    valid_segment = last_seg
                    meta = None

                    if valid_segment:
                        if not meta:
                            try: meta = client.website.get_conversation_metas(website_id, sid)
                            except: meta = {}
                        cust_name = str(meta.get("nickname") or "Customer")
                        meta_data = meta.get("data", {})
                        review_value = meta_data.get("review_value")
                        review_info = f" (Hệ thống ghi nhận khách ĐÃ CHO REVIEW {review_value} sao)" if review_value else ""

                        filtered = []; app_name = site_name
                        last_op_msg = None  # để detect SEEN

                        # Dùng toàn bộ last_seg (không filter theo ngày) để đảm bảo
                        # transcript đủ context: lời chào, lịch sử vấn đề, v.v.
                        # Filter ngày chỉ dùng để quyết định "có chấm hôm nay không"
                        # (đã xử lý ở bước has_activity ở trên).
                        for m in valid_segment:
                            if m.get("type") in ["note", "event"]: continue

                            is_op = m.get("from") == "operator"
                            u_info = m.get("user") or {}
                            content = m.get("content", "")
                            if is_op:
                                op_uid = str(u_info.get("user_id", ""))
                                name = str(u_info.get("nickname") or op_map.get(op_uid) or "Operator")
                                if name.lower() in BOT_NAMES:
                                    continue
                                last_op_msg = m
                                if "DECO" in str(content).upper(): app_name = "DECO"
                                elif "SEARCHPIE" in str(content).upper() or "SEARCH PIE" in str(content).upper(): app_name = "SearchPie"
                                label = name
                            else:
                                label = cust_name
                                last_op_msg = None

                            if m.get("type") == "file" and isinstance(content, dict):
                                content = f"[File: {content.get('name', 'unnamed')} - {content.get('url', '')}]"
                            elif isinstance(content, dict): content = content.get("text") or str(content)
                            filtered.append({"sender": label, "content": str(content), "is_op": is_op})

                        op_meaningful = [f for f in filtered if f["is_op"] and len(f["content"].strip()) > 3]
                        if not op_meaningful:
                            drop_too_short += 1; continue

                        customer_msgs = [f for f in filtered if not f["is_op"]]
                        is_outreach = len(customer_msgs) == 0

                        # Drop toàn bộ outreach chat — khách chưa reply lần nào
                        # (agent chủ động mở chat / reply tin trigger, không có tương tác thực)
                        if is_outreach:
                            drop_too_short += 1; continue

                        customer_seen_no_reply = (
                            last_op_msg is not None and
                            last_op_msg.get("read") == "chat"
                        )
                        outreach_note = ""
                        seen_note = " | ⚠️ KHÁCH ĐÃ SEEN tin nhắn cuối của support nhưng CHƯA REPLY — đây là lý do chưa kết thúc, không trừ điểm support vì điều này." if customer_seen_no_reply else ""
                        supp_info = f"{review_info}{outreach_note}{seen_note}" if (review_info or outreach_note or seen_note) else "Chưa thấy có thông tin review từ hệ thống"
                        transcript = f"--- THÔNG TIN BỔ SUNG: {supp_info} ---\n\n"
                        transcript += f"[Agent được chấm: {sole_agent}]\n\n"
                        for f in filtered:
                            prefix = f"  {f['sender']}: " if f['is_op'] else f"{f['sender']}: "
                            transcript += f"{prefix}{str(f['content']).replace(chr(10), chr(10) + '      ')}\n\n"

                        # Extract real timestamps and msg_count from valid_segment
                        chat_msgs = [m for m in valid_segment if m.get("type") not in ("event", "note", "animation") and m.get("timestamp")]
                        ts_list = [m["timestamp"] for m in chat_msgs]
                        TZ7 = timezone(timedelta(hours=7))
                        seg_start = datetime.fromtimestamp(min(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S") if ts_list else None
                        seg_end   = datetime.fromtimestamp(max(ts_list) / 1000, tz=TZ7).strftime("%Y-%m-%d %H:%M:%S") if ts_list else None

                        all_valid_chats.append({
                            "session_id": sid, "website_id": website_id, "date": target_date_str,
                            "app": app_name, "customer": cust_name, "primary_operator": sole_agent,
                            "is_resolved": conv_is_resolved, "transcript": transcript,
                            "seg_start": seg_start, "seg_end": seg_end,
                            "seg_msg_count": len(chat_msgs),
                        })
        print(f"  🔍 Drop summary: no_msgs={drop_no_msgs}, no_segment={drop_no_segment}, no_ops={drop_no_ops}, too_short={drop_too_short}")
        return all_valid_chats
    except Exception:
        traceback.print_exc()
        return []

def _get_active_prompt() -> str:
    try:
        from database.prompts import get_prompt_content
        return get_prompt_content() or GRADING_CRITERIA
    except Exception:
        return GRADING_CRITERIA


def grade_chat(transcript):
    if not OPENROUTER_API_KEY: return None
    try:
        messages = [
            {"role": "system", "content": _get_active_prompt()},
            *_FEW_SHOT_MESSAGES,
            {"role": "user", "content": f"Chấm đoạn chat sau:\n\n{transcript}"}
        ]
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            data=json.dumps({"model": MODEL, "messages": messages, "response_format": {"type": "json_object"}, "max_tokens": 4096})
        )
        if response.status_code != 200: print(f"    ❌ API Error {response.status_code}: {response.text}")
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"    ❌ Exception in grade_chat: {str(e)}")
        return None

def _hex_to_color(h):
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

SHEET_NAME = "QA Report"

def export_to_gsheet(results, _date_str=None):
    if not GOOGLE_SHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        print("❌ Missing GOOGLE_SHEET_ID or GOOGLE_CREDENTIALS_PATH in .env")
        return

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

    # Lấy hoặc tạo sheet cố định "QA Report"
    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=30)

    # Đọc data hiện có để dedup theo URL (col B)
    existing_rows = ws.get_all_values()
    existing_sids = set()
    existing_data_count = 0  # số data rows thực sự (có Crisp URL)
    if len(existing_rows) > 1:
        for row in existing_rows[1:]:
            if row and len(row) > 1 and row[1].startswith("https://app.crisp.chat"):
                existing_sids.add(row[1])
                existing_data_count += 1

    new_results = [r for r in results if
        f"https://app.crisp.chat/website/{r['website_id']}/inbox/{r['session_id']}" not in existing_sids]

    print(f"📊 Appending {len(new_results)} new chats (skipping {len(results)-len(new_results)} duplicates)...")

    if not new_results and existing_rows:
        print("  ℹ️  No new data to add.")
        return

    # Nếu có rows thừa sau data thật (old summary, blanks) → clear trước khi append
    if len(existing_rows) > 1 + existing_data_count:
        clear_start_1idx = 1 + existing_data_count + 1  # 1-indexed row sau data cuối
        ws.batch_clear([f"A{clear_start_1idx}:Z{clear_start_1idx + 100}"])

    sid = ws.id  # sheet id for batchUpdate

    headers = ["Convo Date", "Chat URL", "App", "Support", "Rating (/10)",
               "Greeting (0.25)", "Grammar (1.25)", "Concise (2.0)", "Listening (1.5)",
               "Tone/Pace (0.75)", "Empathy (0.75)", "Enthusiastic (1.5)", "Probing (1.5)",
               "Solution (3.0)", "Pro-active (2.0)", "Transfer (2.0)", "Resources (0.5)",
               "Extra Mile (1.5)", "Review (1.5)", "Comments", "Resolved"]
    key_map = ["greetings", "grammar", "communication", "listening", "tone_pace", "empathy",
               "enthusiastic", "probing", "solution", "proactiveness", "transferring",
               "resources", "extra_mile", "review_asking"]
    max_scores = [0, 0, 0, 0, 0, 0.25, 1.25, 2.0, 1.5, 0.75, 0.75, 1.5, 1.5, 3.0, 2.0, 2.0, 0.5, 1.5, 1.5, 0]

    _caps = dict(zip(key_map, [0.25, 1.25, 2.0, 1.5, 0.75, 0.75, 1.5, 1.5, 3.0, 2.0, 2.0, 0.5, 1.5, 1.5]))

    def _score(g, key):
        return min(float(g.get(key, {}).get('score', 0)), _caps.get(key, 9999))

    new_data_rows = []
    for chat in new_results:
        g = chat.get('grading', {}).get('criteria', {})
        url = f"https://app.crisp.chat/website/{chat['website_id']}/inbox/{chat['session_id']}"
        capped_scores = [_score(g, k) for k in key_map]
        total_capped = round(sum(capped_scores) / 2, 2)
        new_data_rows.append([
            chat['date'], url, chat['app'], chat['primary_operator'],
            total_capped,
            *capped_scores,
            chat.get('grading', {}).get('overall_summary', ""),
            "✅ Resolved" if chat.get('is_resolved') else "🔄 Open"
        ])

    # Luôn đảm bảo header ở row 1 (idempotent)
    ws.update([headers], "A1", value_input_option="USER_ENTERED")

    # Append new rows
    if new_data_rows:
        ws.append_rows(new_data_rows, value_input_option="USER_ENTERED")

    # --- Summary: đọc toàn bộ data hiện tại (bao gồm cả mới append) để tính avg ---
    all_rows = ws.get_all_values()
    agent_stats = {}
    for row in all_rows[1:]:  # skip header
        if len(row) < 5: continue
        agent = row[3]; score_str = row[4]
        try:
            score = float(score_str)
            agent_stats.setdefault(agent, []).append(score)
        except: continue

    summary_rows = [["Support", "Avg Score (/10)", "Total Chats"]]
    for agent, scores in sorted(agent_stats.items()):
        summary_rows.append([agent, round(sum(scores) / len(scores), 2), len(scores)])

    # Summary đặt bên dưới data, cách 2 dòng
    # Dùng actual data count (không tính summary rows cũ) để tính vị trí
    total_data_rows = 1 + existing_data_count + len(new_data_rows)  # header + all data
    summary_start_row = total_data_rows + 2  # 1-indexed row

    # Ghi summary rows vào sheet
    ws.update(summary_rows, f"A{summary_start_row}", value_input_option="USER_ENTERED")

    # --- Formatting via batchUpdate ---
    reqs = []

    def repeat_cell(r0, r1, c0, c1, fmt, fields):
        reqs.append({"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": fmt},
            "fields": f"userEnteredFormat({fields})"
        }})

    def set_col_width(c0, c1, px):
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"
        }})

    # Header row — main table (21 cols: 0–20 inclusive)
    repeat_cell(0, 1, 0, 21, {
        "backgroundColor": _hex_to_color("1F4E78"),
        "textFormat": {"foregroundColor": _hex_to_color("FFFFFF"), "bold": True},
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"
    }, "backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy")

    # Header row — summary table (below main data, cols A-C)
    sum_r0 = summary_start_row - 1  # 0-indexed
    repeat_cell(sum_r0, sum_r0 + 1, 0, 3, {
        "backgroundColor": _hex_to_color("1F4E78"),
        "textFormat": {"foregroundColor": _hex_to_color("FFFFFF"), "bold": True},
        "horizontalAlignment": "CENTER"
    }, "backgroundColor,textFormat,horizontalAlignment")

    # Per-row: score color + deduction highlights + justification notes
    # new data rows start at 0-indexed: 1 (header) + existing_data_count
    new_data_start_0idx = 1 + existing_data_count
    note_reqs = []
    for offset, chat in enumerate(new_results):
        row_idx = new_data_start_0idx + offset  # 0-indexed row in sheet
        g = chat.get('grading', {}).get('criteria', {})
        capped_scores_row = [_score(g, k) for k in key_map]
        score = round(sum(capped_scores_row) / 2, 2)
        score_color = "FF6B6B" if score < 7 else "FFD966" if score < 9 else "6BCB77"
        repeat_cell(row_idx, row_idx + 1, 4, 5, {"backgroundColor": _hex_to_color(score_color)}, "backgroundColor")

        for col_offset, key in enumerate(key_map):
            col_idx = 5 + col_offset
            val = g.get(key, {}).get('score', 0)
            if val < max_scores[col_idx]:
                repeat_cell(row_idx, row_idx + 1, col_idx, col_idx + 1, {"backgroundColor": _hex_to_color("FCE4D6")}, "backgroundColor")
            justification = g.get(key, {}).get('justification', "")
            if justification:
                note_reqs.append({"updateCells": {
                    "range": {"sheetId": sid, "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
                    "rows": [{"values": [{"note": justification}]}],
                    "fields": "note"
                }})

    # Summary score colors (col B = index 1, below main table) — dùng sorted để khớp với summary_rows
    for s_idx, (agent, scores) in enumerate(sorted(agent_stats.items()), 1):
        avg = sum(scores) / len(scores) if scores else 0
        score_color = "FF6B6B" if avg < 7 else "FFD966" if avg < 9 else "6BCB77"
        r = sum_r0 + s_idx
        repeat_cell(r, r + 1, 1, 2, {"backgroundColor": _hex_to_color(score_color)}, "backgroundColor")

    # Column widths
    set_col_width(0, 1, 100)   # Date / Summary Support
    set_col_width(1, 2, 260)   # URL / Summary Avg
    set_col_width(2, 3, 100)   # App / Summary Count
    set_col_width(3, 4, 120)   # Support
    set_col_width(4, 5, 80)    # Rating
    set_col_width(5, 19, 70)   # Criteria
    set_col_width(19, 20, 360) # Comments
    set_col_width(20, 21, 110) # Resolved

    # Freeze header row
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"
    }})

    spreadsheet.batch_update({"requests": reqs + note_reqs})
    sheet_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit#gid={sid}"
    print(f"✅ Exported to '{SHEET_NAME}': {sheet_url}")

def _fmt_elapsed(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"

_SCORE_CAPS = {"greetings": 0.25, "grammar": 1.25, "communication": 2.0, "listening": 1.5,
               "tone_pace": 0.75, "empathy": 0.75, "enthusiastic": 1.5, "probing": 1.5,
               "solution": 3.0, "proactiveness": 2.0, "transferring": 2.0, "resources": 0.5,
               "extra_mile": 1.5, "review_asking": 1.5}

def _parse_and_cap(raw):
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    data = json.loads(raw)
    criteria = data.get('criteria', {})
    if len(criteria) < 14:
        # LLM trả về format sai (thường do transcript quá ngắn/không có nội dung hỗ trợ)
        raise ValueError(f"Incomplete criteria ({len(criteria)}/14). Response keys: {list(data.keys())}")
    for k, cap in _SCORE_CAPS.items():
        if k in criteria:
            criteria[k]['score'] = min(float(criteria[k].get('score', 0)), cap)
    total_20 = sum(item.get('score', 0) for item in criteria.values())
    data['total_score_20'] = round(total_20, 2)
    data['final_score_10'] = round(total_20 / 2, 2)
    return data

def _grade_one(args):
    """Grade một chat, retry tối đa 10 lần. Dùng cho parallel."""
    i, total, chat = args
    chat_start = time.time()
    label = f"{chat.get('primary_operator', '?')} | {chat.get('app', '?')}"
    print(f"  [{i}/{total}] {label} — {chat['session_id']}", flush=True)
    for attempt in range(1, 11):
        grade_raw = grade_chat(chat['transcript'])
        if not grade_raw:
            print(f"    ❌ No grading returned (attempt {attempt}/10), retry sau 5s...")
            time.sleep(5)
            continue
        try:
            grading_data = _parse_and_cap(grade_raw)
            chat['grading'] = grading_data
            print(f"    ✅ {grading_data['final_score_10']}/10 — {_fmt_elapsed(time.time() - chat_start)}", flush=True)
            return chat
        except Exception as e:
            wait = min(5 * attempt, 60)
            print(f"    ⚠️  JSON Parse Error (attempt {attempt}/10): {e} — retry sau {wait}s")
            time.sleep(wait)
    print(f"    ❌ Failed after 10 attempts: {label} — {chat['session_id']}")
    return None

def _grade_and_export(chats, date_str, is_regraded=False):
    if not chats:
        print(f"  No chats found for {date_str}.")
        return
    suffix = "_regraded" if is_regraded else ""
    print(f"⚖️ Grading {len(chats)} chats for {date_str} (parallel)...")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    args_list = [(i, len(chats), chat) for i, chat in enumerate(chats, 1)]
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_grade_one, a): a for a in args_list}
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                results.append(result)

    if results:
        date_nodash = date_str.replace('-', '')
        output_json = f"./report/qa_report_{date_nodash}{suffix}.json"
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON saved: {output_json}")
        sheet_name = date_str + (" (regraded)" if is_regraded else "")
        export_to_gsheet(results, sheet_name)
    else:
        print(f"  No results graded for {date_str}.")


def main():
    load_few_shot_examples()
    run_start = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single date (YYYY-MM-DD), default today")
    parser.add_argument("--from", dest="date_from", help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", help="End date for range (YYYY-MM-DD)")
    parser.add_argument("--regrade", help="Path to existing JSON file for re-grading")
    args = parser.parse_args()

    if args.regrade:
        if not os.path.exists(args.regrade):
            print(f"❌ File {args.regrade} not found.")
            return
        print(f"⚖️ Re-grading chats from {args.regrade}...")
        with open(args.regrade, 'r', encoding='utf-8') as f:
            chats = json.load(f)
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        _grade_and_export(chats, date_str, is_regraded=True)
    elif args.date_from and args.date_to:
        d_from = datetime.strptime(args.date_from, "%Y-%m-%d")
        d_to = datetime.strptime(args.date_to, "%Y-%m-%d")
        if d_from > d_to:
            print("❌ --from phải trước --to.")
            return
        total_days = (d_to - d_from).days + 1
        print(f"📅 Date range: {args.date_from} → {args.date_to} ({total_days} ngày)")
        current = d_from
        while current <= d_to:
            date_str = current.strftime("%Y-%m-%d")
            print(f"\n{'='*50}")
            print(f"📆 {date_str}")
            print(f"{'='*50}")
            chats = fetch_chats(date_str)
            _grade_and_export(chats, date_str)
            current += timedelta(days=1)
    else:
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        chats = fetch_chats(date_str)
        _grade_and_export(chats, date_str)

    print(f"\n⏱ Tổng thời gian: {_fmt_elapsed(time.time() - run_start)}")

    print(f"🏁 Done in {_fmt_elapsed(time.time() - run_start)}")

if __name__ == "__main__":
    main()
