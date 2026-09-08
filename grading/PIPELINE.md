# Pipeline Documentation: analyzer_v2 & scheduler

## Tổng quan

Hệ thống QA tự động chấm điểm các cuộc hội thoại support của PieLab mỗi ngày lúc 09:00 sáng giờ Việt Nam.

```
Crisp API → fetch_chats() → _grade_one() → MongoDB (grading + sumtag)
```

---

## analyzer_v2.py

File này chứa toàn bộ logic **lấy dữ liệu từ Crisp** và **chấm điểm bằng LLM**.

### 1. load_few_shot_examples()

**Lấy gì:** File `qa_references.json` — danh sách ví dụ mẫu đã chấm tay.

**Làm gì:**
- Nhóm ví dụ theo `label` (e.g. `perfect_10`, `solution_zero`, `review_only`, `transferring_zero`, `solution_deducted`, `communication_deducted`)
- Mỗi lần gọi random chọn 1 ví dụ từ mỗi nhóm, tối đa 4 ví dụ
- Cắt transcript dài hơn 6000 ký tự
- Ghi vào biến global `_FEW_SHOT_MESSAGES` dạng `[{role: user, content: transcript}, {role: assistant, content: json_output}, ...]`

**Lưu gì:** Không lưu — chỉ đưa vào memory để dùng trong `grade_chat()`.

---

### 2. fetch_chats(target_date_str)

Đây là hàm **trung tâm** của toàn bộ pipeline. Trả về danh sách các chat cần chấm trong ngày.

**Lấy gì từ Crisp API:**

| Bước | API call | Mục đích |
|------|----------|----------|
| 1 | `plugin.list_all_connect_websites()` | Lấy danh sách tất cả websites đang kết nối |
| 2 | `website.list_website_operators(website_id)` | Lấy map `user_id → tên operator` cho mỗi website |
| 3 | `website.search_conversations(website_id, page, filter_date_start=...)` | Lấy conversations cập nhật trong ngày, cả resolved lẫn unresolved (2 lượt) |
| 4 | `website.get_messages_in_conversation(website_id, sid)` | Lấy toàn bộ tin nhắn của từng conversation (phân trang, newest-first) |
| 5 | `website.get_conversation_metas(website_id, sid)` | Lấy tên khách hàng và review_value |

**Làm gì với dữ liệu:**

**a) Tìm `valid_seg` — segment cần chấm:**

Mỗi conversation được chia thành các **segment** tách nhau bởi sự kiện `resolved`. Segment cuối cùng **có hoạt động trong ngày target** (tin nhắn thực, không phải event/note) là `valid_seg`.

```
Conversation messages:
  [msg1, msg2, EVENT:resolved, msg3, msg4, EVENT:resolved, msg5, msg6]
         segment 0              segment 1                   segment 2
                                                            ↑ valid_seg nếu msg5/msg6 trong ngày
```

**b) Xác định `primary_operator`:**
- Nếu chỉ 1 agent gửi tin (không tính bot `PieLab Support`/`PieLab`) → dùng agent đó
- Nếu nhiều agent → lấy agent có tin nhắn nhiều nhất **trong ngày target**

**c) Xây dựng transcript:**
- Lọc bỏ note và event
- Phát hiện app name từ nội dung tin agent: nếu mention `"DECO"` → `app = "DECO"`, nếu `"SEARCHPIE"` → `app = "SearchPie"`, mặc định là site name
- Bổ sung thông tin phụ: review value (nếu có), cảnh báo "khách đã seen chưa reply"
- Format: `THÔNG TIN BỔ SUNG → [Agent được chấm] → transcript`

**d) Extract timestamps thực:**
```python
chat_msgs = [m for m in valid_segment if type not in (event, note, animation)]
seg_start = min(timestamps) → "YYYY-MM-DD HH:MM:SS" (UTC+7)
seg_end   = max(timestamps) → "YYYY-MM-DD HH:MM:SS" (UTC+7)
seg_msg_count = len(chat_msgs)
```

**Conversation bị loại bỏ nếu:**
- Không lấy được tin nhắn (`drop_no_msgs`)
- Không có segment hoặc không có segment nào có activity trong ngày (`drop_no_segment`)
- Không tìm được agent nào trong segment (`drop_no_ops`)
- Transcript quá ngắn — dưới 2 tin hoặc không có tin agent ý nghĩa (`drop_too_short`)

**Trả về:** List các dict:
```python
{
  "session_id", "website_id", "date", "app",
  "customer", "primary_operator", "is_resolved",
  "transcript",       # nội dung dùng để chấm
  "seg_start",        # thời điểm tin nhắn đầu tiên trong segment (UTC+7)
  "seg_end",          # thời điểm tin nhắn cuối cùng (UTC+7)
  "seg_msg_count",    # số tin nhắn thực trong segment
}
```

---

### 3. grade_chat(transcript)

**Lấy gì:** Transcript text.

**Làm gì:**
- Gọi OpenRouter API (`/v1/chat/completions`) với:
  - System prompt = grading criteria (14 tiêu chí, 20 điểm) — hoặc prompt custom từ DB nếu có
  - Few-shot examples từ `_FEW_SHOT_MESSAGES`
  - User message = transcript
- Yêu cầu response dạng `json_object`

**Trả về:** Raw JSON string từ LLM.

---

### 4. _parse_and_cap(raw)

**Làm gì:**
- Parse JSON (xử lý cả trường hợp có ` ```json ``` ` wrapper)
- Kiểm tra đủ 14 tiêu chí
- Cap điểm theo `_SCORE_CAPS` (e.g. solution tối đa 3.0, greetings tối đa 0.25)
- Tính `total_score_20` và `final_score_10 = total / 2`

**Trả về:** Dict grading đã chuẩn hóa.

---

### 5. _grade_one(args)

**Làm gì:**
- Wrapper xử lý 1 chat, retry tối đa 3 lần khi JSON lỗi
- Thread-safe, dùng cho `ThreadPoolExecutor`

**Trả về:** Chat dict với field `"grading"` đã gắn vào, hoặc `None` nếu fail.

---

### 6. _grade_and_export(chats, date_str)

**Làm gì:**
- Chạy `_grade_one` song song với `ThreadPoolExecutor(max_workers=5)`
- Lưu kết quả ra file `./report/qa_report_YYYYMMDD.json`

---

## scheduler.py

File này **điều phối** toàn bộ quy trình mỗi ngày và lưu vào MongoDB.

### Cấu trúc

```
run_daily_job()
  ├── fetch_chats(date_str)           ← từ analyzer_v2
  ├── _grade_date(chats, date_str)    ← parallel grade + save JSON
  └── _save_to_mongo()                ← MongoDB grading + sumtag
```

---

### 1. _grade_date(chats, date_str)

**Làm gì:**
- Parallel grade via `ThreadPoolExecutor(max_workers=5)`
- Lưu ra `qa_report_YYYYMMDD.json` (cùng thư mục, không phải `./report/`)

**Trả về:** List chat dict đã có field `grading`.

---

### 2. _generate_summary_and_tags(transcript)

**Làm gì:**
- 1 lần gọi LLM (OpenRouter, cùng model với grading) với prompt yêu cầu:
  - Tóm tắt dạng bullet point tiếng Việt: vấn đề, hành động agent, thái độ khách
  - Cuối response có ` ```json {"tags": ["...", "...", "..."]} ``` `
- Parse tách phần summary text (trước JSON block) và tags (trong JSON block)

**Trả về:** `(summary_text, tags_list)`

---

### 3. _save_to_mongo(results)

**Làm gì — theo thứ tự:**

**Bước 1 — Dedup:**
```python
saved_keys = get_all_saved_keys()  # query cả grading_deco + grading_searchpie
to_save = [c for c in results if (c["session_id"], c["date"]) not in saved_keys]
```

**Bước 2 — Tạo summary + tags song song:**
```python
ThreadPoolExecutor(max_workers=5) → _generate_summary_and_tags(transcript)
```

**Bước 3 — Lưu grading vào MongoDB:**
```python
upsert_many(records)
# → routes theo app:
#     "DECO"       → collection grading_deco
#     "SearchPie"  → collection grading_searchpie
#     unknown      → bỏ qua
```

**Bước 4 — Lưu sumtag vào MongoDB (1 record / chat):**
```python
sumtag_upsert(
  session_id, date, tags, summary,
  website_id, app, primary_operator,
  start=seg_start,      # timestamp thực đầu segment
  end=seg_end,          # timestamp thực cuối segment
  msg_count=seg_msg_count,
)
# → routes theo app:
#     "DECO"       → collection sumtag_deco
#     "SearchPie"  → collection sumtag_searchpie
#     unknown      → bỏ qua
```

---

### 4. run_daily_job(date_str=None)

**Làm gì:**
- Mặc định: chấm **ngày hôm qua** (tính theo UTC+7)
- Có thể truyền `date_str` để chấm ngày cụ thể
- Gọi 3 bước: fetch → grade → save mongo
- Log toàn bộ vào `scheduler.log`

---

### 5. Scheduling — _seconds_until_9am_vn()

```python
_TZ7 = timezone(timedelta(hours=7))  # UTC+7, hardcoded — không phụ thuộc server timezone

def _seconds_until_9am_vn() -> float:
    now = datetime.now(_TZ7)
    target = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return (target - now).total_seconds()
```

**Vòng lặp chính:**
```
Khởi động → nếu đã qua 9h VN hôm nay → chấm bổ sung ngày hôm qua ngay
→ vòng lặp: sleep đến 9h VN → run_daily_job() → lặp lại
```

---

## MongoDB Collections

| Collection | Nội dung | Primary key |
|------------|----------|-------------|
| `grading_deco` | Grading chi tiết cho app DECO | `(session_id, date)` |
| `grading_searchpie` | Grading chi tiết cho app SearchPie | `(session_id, date)` |
| `sumtag_deco` | Summary + tags cho segment DECO | `(session_id, date)` |
| `sumtag_searchpie` | Summary + tags cho segment SearchPie | `(session_id, date)` |

Mỗi record có thêm `uuid` = UUID5 từ `"session_id:date"` — dùng để cross-reference giữa grading và sumtag.

---

## Environment Variables (.env)

| Variable | Dùng ở | Mục đích |
|----------|--------|----------|
| `CRISP_IDENTIFIER` | analyzer_v2 | Crisp plugin authentication |
| `CRISP_KEY` | analyzer_v2 | Crisp plugin authentication |
| `OPENROUTER_API_KEY` | analyzer_v2, scheduler | LLM grading + summary |
| `OPENROUTER_MODEL` | analyzer_v2, scheduler | Model ID (default: `google/gemini-2.0-flash-001`) |

---

## Chạy thủ công

```bash
# Chấm ngày cụ thể (không lưu MongoDB)
python grading/analyzer_v2.py --date 2026-05-04

# Chấm khoảng ngày
python grading/analyzer_v2.py --from 2026-05-01 --to 2026-05-04

# Chấm lại từ file JSON đã có
python grading/analyzer_v2.py --regrade ./report/qa_report_20260504.json

# Scheduler: chấm ngay hôm qua (test)
python grading/scheduler.py --now

# Scheduler: chấm ngày cụ thể rồi thoát
python grading/scheduler.py --date 2026-05-04

# Scheduler: chạy daemon, tự chấm 9h mỗi ngày
python grading/scheduler.py
```
