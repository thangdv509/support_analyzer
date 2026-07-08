# Support Analyzer

Hệ thống QA tự động chấm điểm hội thoại support của PieLab (DECO & SearchPie) từ Crisp, lưu vào MongoDB, và xuất báo cáo Google Sheets.

---

## Cài đặt

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Tạo file `.env` (xem mục [Biến môi trường](#biến-môi-trường)).

---

## Các file chính

### `scheduler.py` — Chấm điểm tự động hàng ngày

Chạy daemon, tự động chấm ngày hôm trước lúc **09:00 sáng giờ Việt Nam** mỗi ngày.

Quy trình mỗi ngày: fetch Crisp → chấm LLM (song song) → xuất Google Sheet → lưu MongoDB.

```bash
# Chạy daemon (chấm 9h sáng mỗi ngày)
python scheduler.py

# Chấm ngay lập tức (ngày hôm qua)
python scheduler.py --now

# Chấm ngày cụ thể rồi thoát
python scheduler.py --date 2026-05-10
```

**Lưu vào:**
- Google Sheet `"Support Analyzer"` (append + tính lại summary)
- MongoDB `grading_deco` / `grading_searchpie`
- MongoDB `sumtag_deco` / `sumtag_searchpie`
- File `qa_report_YYYYMMDD.json` (thư mục hiện tại)

---

### `analyzer_v2.py` — Chấm điểm thủ công

Chấm thủ công theo ngày hoặc khoảng ngày, xuất ra sheet riêng `"QA Report"`.

```bash
# Chấm hôm nay
python analyzer_v2.py

# Chấm ngày cụ thể
python analyzer_v2.py --date 2026-05-10

# Chấm khoảng ngày
python analyzer_v2.py --from 2026-05-01 --to 2026-05-10

# Chấm lại từ file JSON đã có (không fetch Crisp lại)
python analyzer_v2.py --regrade ./report/qa_report_20260510.json
```

**Lưu vào:**
- Google Sheet `"QA Report"`
- File `./report/qa_report_YYYYMMDD.json`

---

### `main.py` — Chấm thủ công + lưu MongoDB

Giống `analyzer_v2.py` nhưng **có lưu vào MongoDB** và tạo sheet theo timestamp (không ghi đè).

```bash
python main.py
python main.py --date 2026-05-10
python main.py --from 2026-05-01 --to 2026-05-10
python main.py --regrade qa_report_20260510.json
python main.py --no-mongo    # bỏ qua MongoDB, không cần tunnel
```

---

### `reexport_sheet.py` — Xuất lại sheet từ MongoDB

Dùng khi sheet bị lỗi format. Xóa sheet và ghi lại toàn bộ từ MongoDB.

```bash
# Xuất lại khoảng ngày cụ thể
python reexport_sheet.py --from 2026-05-03 --to 2026-05-18

# Xuất lại toàn bộ dữ liệu trong DB
python reexport_sheet.py
```

---

### `export_history.py` — Xuất lịch sử vào sheet tùy chọn

Xuất lịch sử nhiều ngày vào một sheet Google Sheets tùy đặt tên. Ưu tiên dùng data MongoDB, ngày nào thiếu thì fetch + chấm mới.

```bash
python export_history.py --from 2026-01-01
python export_history.py --from 2026-01-01 --to 2026-04-30
python export_history.py --from 2026-01-01 --sheet "History Q1 2026"
```

---

### `crawl.py` — Crawl Crisp về JSON

Crawl dữ liệu hội thoại Crisp ra file JSON thô (không chấm điểm). Dùng để lấy dữ liệu lịch sử hoặc debug.

```bash
python crawl.py --date 2026-05-10
python crawl.py --from 2026-03-01 --to 2026-03-31
python crawl.py --date 2026-05-10 --website <website_id>
```

---

### `build_references_from_db.py` — Tạo few-shot examples

Đọc dữ liệu đã chấm từ MongoDB, chọn các ví dụ đại diện theo nhãn (perfect_10, solution_zero, ...) và tạo file `qa_references.json` dùng cho few-shot prompting khi chấm.

Chạy lại mỗi khi muốn cập nhật ví dụ mẫu.

```bash
python build_references_from_db.py
```

---

### `migrate_collections.py` — Migration dữ liệu cũ

Chuyển dữ liệu từ collections cũ (`deco_chat`, `sumtag`) sang collections mới chia theo app.

```bash
python migrate_collections.py            # chạy thật
python migrate_collections.py --dry-run  # chỉ xem thống kê, không ghi
```

---

### `import_sumtag.py` — Import sumtag từ JSON lịch sử

Import file JSON crawl lịch sử vào collection sumtag, sau đó crawl catch-up đến hiện tại.

```bash
python import_sumtag.py
python import_sumtag.py --no-import          # chỉ catch-up, bỏ qua import JSON
python import_sumtag.py --from 2026-04-01    # catch-up từ ngày cụ thể
```

---

### `mcp_server/server.py` — MCP Server

Cung cấp tools cho Claude (MCP) để query dữ liệu QA và quản lý prompt.

| Tool | Công dụng |
|------|-----------|
| `qa_overview` | Tổng quan điểm theo khoảng ngày + LLM summary |
| `qa_by_date` | Chi tiết từng chat trong ngày |
| `qa_by_agent` | Điểm và phân tích theo agent |
| `qa_regrade` | Chấm lại 1 chat với prompt tùy chọn |
| `qa_prompt_get` | Lấy prompt đang active |
| `qa_prompt_update` | Lưu version prompt mới vào DB |
| `qa_prompt_suggest` | LLM gợi ý cải thiện prompt từ feedback |

```bash
python -m mcp_server.server
```

---

## Database (`database/`)

| File | Công dụng |
|------|-----------|
| `connection.py` | Kết nối MongoDB |
| `tunnel.py` | Quản lý SSH tunnel (tự mở/đóng) |
| `deco_chat.py` | CRUD cho `grading_deco` / `grading_searchpie` |
| `sumtag.py` | CRUD cho `sumtag_deco` / `sumtag_searchpie` |
| `prompts.py` | Versioning prompt chấm điểm |

### MongoDB Collections

| Collection | Nội dung | Primary key |
|------------|----------|-------------|
| `grading_deco` | Kết quả chấm điểm app DECO | `(session_id, date)` |
| `grading_searchpie` | Kết quả chấm điểm app SearchPie | `(session_id, date)` |
| `sumtag_deco` | Summary + tags segment DECO | `(session_id, date)` |
| `sumtag_searchpie` | Summary + tags segment SearchPie | `(session_id, date)` |
| `prompts` | Lịch sử versions prompt chấm điểm | `version` |

---

## Biến môi trường

Tạo file `.env` ở thư mục gốc:

```env
# Crisp API
CRISP_IDENTIFIER=...
CRISP_KEY=...

# OpenRouter (LLM)
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=google/gemini-2.0-flash-001   # tùy chọn

# Google Sheets
GOOGLE_SHEET_ID=...
GOOGLE_CREDENTIALS_PATH=credentials.json

# MongoDB
MONGO_HOST=127.0.0.1
MONGO_PORT=27018
MONGO_DB=support_analyzer

# SSH Tunnel tới MongoDB
SSH_TUNNEL_HOST=...
SSH_TUNNEL_PORT=22
SSH_TUNNEL_USER=...
SSH_TUNNEL_KEY=/path/to/key.pem    # nếu dùng key file
SSH_TUNNEL_REMOTE=10.x.x.x:27017
```

---

## Google Sheets

| Sheet | Tạo bởi | Nội dung |
|-------|---------|----------|
| `Support Analyzer` | `scheduler.py` | Chạy tự động, cộng dồn theo ngày |
| `QA Report` | `analyzer_v2.py` | Chạy thủ công |
| `<timestamp>` | `main.py` | Mỗi lần chạy tạo sheet mới |
| Tên tùy chọn | `export_history.py` | Xuất lịch sử |


Giờ chỉ cần một lệnh:


source venv/bin/activate
python -m mcp_server.server --http
Output sẽ in ra URL ngrok ngay:


🌐 MCP server  : http://0.0.0.0:8765/mcp
🔗 Ngrok URL   : https://xxxx-xxx.ngrok-free.app/mcp
👉 Thêm vào Claude.ai connector: https://xxxx-xxx.ngrok-free.app/mcp
Copy URL đó vào claude.ai → Settings → Integrations → Add MCP server là xong. Nếu chưa có ngrok auth token thì chạy ngrok config add-authtoken <token> một lần trước.

Bước 1 — Tạo Google OAuth credentials
Vào console.cloud.google.com → APIs & Services → Credentials
Create Credentials → OAuth 2.0 Client ID → chọn Web application
Ở phần Authorized redirect URIs, thêm:

https://<ngrok-domain>/oauth/callback
(nếu dùng ngrok static domain thì URI này cố định, ngrok free có 1 static domain)
Copy Client ID và Client secret vào .env:

GOOGLE_CLIENT_ID="xxx.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="GOCSPX-..."
Bước 2 — Thêm email được phép truy cập

cd support_analyzer && source venv/bin/activate
python -m mcp_server.server --add-email vietthang.doan@secomus.com
python -m mcp_server.server --add-email colleague@secomus.com
python -m mcp_server.server --list-emails
Bước 3 — Chạy server

python -m mcp_server.server --http
Output:


🔗 Ngrok URL   :                                                                                                                                                                                                                                                                                                
🔐 Login URL   : https://xyz.ngrok-free.app/login
Bước 4 — Lấy token
Mở browser vào https://xyz.ngrok-free.app/login → đăng nhập Google → token hiển thị trên màn hình.

Hoặc Claude.ai sẽ tự chạy OAuth flow (hiện nút Authenticate) khi thêm MCP connector.

Quản lý email

python -m mcp_server.server --add-email new@example.com
python -m mcp_server.server --remove-email old@example.com
python -m mcp_server.server --list-emails


./start_ui.sh

kill $(pgrep -u thangdv uvicorn) 2>/dev/null; sleep 1; ./start_ui.sh --prod
                                                                                                                                                                                                                                                                                                                                                     