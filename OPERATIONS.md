# Support Analyzer — Operations Guide

Hệ thống QA tự động chấm điểm hội thoại support của PieLab (**DECO** & **SearchPie**) lấy từ Crisp, chấm bằng LLM (qua OpenRouter), lưu vào MongoDB, và hiển thị qua QA Dashboard (React) + MCP server (cho Claude).

> Xem `README.md` để biết chi tiết từng script CLI. File này tập trung vào **sử dụng dashboard, deploy, và vận hành/quản lý hệ thống**.

---

## 1. Kiến trúc tổng quan

```
Crisp API  ──►  grading/analyzer_v2.py (fetch + chấm điểm LLM)  ──►  MongoDB

MongoDB  ──►  api/main.py (FastAPI)  ──►  ui/ (React + AG-Grid)   [QA Dashboard]
         └─►  mcp_server/server.py (MCP)                          [Claude connector]

grading/scheduler.py — daemon chấm điểm tự động mỗi ngày lúc 9h sáng
```

Code được tổ chức theo tính năng: `grading/` (pipeline chấm điểm), `scripts/` (bảo trì/one-off), `api/` + `ui/src/features/` (dashboard), `mcp_server/` (Claude connector), `database/` (data-access layer dùng chung). Xem `README.md` mục "Cấu trúc thư mục" để biết chi tiết từng file nằm ở đâu.

- **Crisp**: một website/inbox chung cho cả DECO và SearchPie — phân loại app dựa trên nội dung chat, không phải theo site riêng.
- **OpenRouter**: toàn bộ model LLM dùng trong hệ thống (chấm điểm, tóm tắt, summarize agent, completion-check) đọc từ **một biến duy nhất** `OPENROUTER_MODEL` trong `.env`. Riêng `EMBEDDING_MODEL` (dùng cho RAG vector search trong `docs/app_guides/`) là model embedding, tách biệt vì không thể dùng chung với model chat.
- **MongoDB**: qua SSH tunnel (tự mở/đóng bởi `database/tunnel.py`), không expose public.

---

## 2. Biến môi trường liên quan tới deploy/quản lý

```env
# Google OAuth (đăng nhập Dashboard UI + MCP connector)
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=http://<domain>/api/auth/callback

# UI Dashboard auth
JWT_SECRET=...                      # đổi giá trị thật khi deploy production
JWT_EXPIRE_HOURS=168
API_PORT=5090
BACKEND_URL=http://<domain>         # PHẢI trỏ đúng domain đang chạy (xem mục 4.3)
FRONTEND_URL=http://<domain>
ADMIN_EMAILS=email1@secomus.com,email2@secomus.com   # tự động cấp quyền admin khi login lần đầu

# MCP server (tuỳ chọn, khi expose qua ngrok)
PUBLIC_URL=https://xxxx.ngrok-free.app
```

> ⚠️ **Lưu ý khi dev local**: nếu đổi tạm `BACKEND_URL`/`FRONTEND_URL`/`GOOGLE_REDIRECT_URI` sang `localhost` để test OAuth, nhớ **trả lại giá trị domain thật** trước khi deploy production — nếu không login sẽ bị redirect nhầm sang localhost trên server thật.

---

## 3. QA Dashboard (UI + API)

### Chạy local (dev)

```bash
./start_ui.sh
# FastAPI  → http://localhost:8000  (--reload)
# Vite dev → http://localhost:5173  (HMR)
```

### Watch mode (build lại tự động, serve qua FastAPI luôn — gần giống prod)

```bash
./start_ui.sh --watch
# → http://localhost:8000
```

### Production (build 1 lần, serve qua FastAPI)

```bash
./start_ui.sh --prod
# → http://0.0.0.0:8000 (hoặc $API_PORT trong .env)
```

Cả 3 mode đều tự `fuser -k` port cũ trước khi start nên không cần tắt thủ công trước — nhưng nếu chạy trên server dùng chung, nhớ kiểm tra không giết nhầm process của người khác.

### Đăng nhập & phân quyền

Google OAuth → JWT cookie (`qa_session`, hạn `JWT_EXPIRE_HOURS`). 3 role:

| Role | Quyền |
|------|-------|
| `admin` | Toàn quyền: xem/thêm/sửa role của bất kỳ ai |
| `manager` | Thêm được `support`, xem danh sách user, dùng Agent Summarize |
| `support` | Không có quyền quản lý user |

Email trong `ADMIN_EMAILS` (`.env`) tự động được cấp `admin` ngay lần đăng nhập đầu tiên. Quản lý user còn lại thực hiện trực tiếp trong tab **User Management** trên UI.

---

## 4. Deploy lên server

### 4.1. Lần đầu

```bash
ssh <user>@<server>
cd /path/to/support_analyzer
git clone <repo> .   # hoặc git pull nếu đã có
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cd ui && npm install && cd ..
```

Tạo `.env` trên server với **domain thật** (không phải localhost) cho `BACKEND_URL`, `FRONTEND_URL`, `GOOGLE_REDIRECT_URI`, và nhớ thêm đúng redirect URI này vào Google Cloud Console (APIs & Services → Credentials → OAuth Client → Authorized redirect URIs).

```bash
./start_ui.sh --prod
```

Nên chạy trong `tmux`/`screen`/`nohup` để không chết khi đóng SSH session, ví dụ:

```bash
tmux new -s support_analyzer
./start_ui.sh --prod
# Ctrl+B, D để detach
```

### 4.2. Cập nhật code (pull code mới)

```bash
git pull
# nếu backend đổi: không cần build gì thêm, chỉ cần restart
# nếu frontend (ui/) đổi: phải build lại — start_ui.sh --prod tự làm việc này

kill $(pgrep -u <user> uvicorn) 2>/dev/null; sleep 1
./start_ui.sh --prod
```

> Nếu `git pull` xong mà code trên UI không đổi — kiểm tra lại có đang chạy nhầm process `--prod` cũ (asset cũ trong `api/static/`) hay chưa restart uvicorn.

### 4.3. Sự cố hay gặp: OAuth redirect nhầm domain

Nguyên nhân: `.env` trên server bị để `BACKEND_URL`/`GOOGLE_REDIRECT_URI` trỏ về `localhost` (thường do copy từ máy dev). Sửa lại đúng domain production trong `.env` **và** trong Google Cloud Console → Authorized redirect URIs, restart lại service.

### 4.4. Scheduler tự động (chấm điểm hàng ngày)

Chạy `grading/scheduler.py` như một daemon riêng (không chung tiến trình với dashboard):

```bash
tmux new -s scheduler
source venv/bin/activate
python grading/scheduler.py
```

Kiểm tra log tại `scheduler.log` (ghi ở thư mục chạy lệnh — luôn chạy từ repo root) — nếu không có entry mới trong nhiều ngày nghĩa là scheduler đã bị chết (session tmux bị đóng, server restart, v.v.), cần khởi động lại thủ công.

> ⚠️ Sau khi deploy bản tái cấu trúc này, **lệnh chạy scheduler đã đổi** từ `python scheduler.py` sang `python grading/scheduler.py` — nhớ dùng lệnh mới khi restart tmux session trên server.

---

## 5. Quản lý dữ liệu & vận hành

### 5.1. MongoDB Collections

| Collection | Nội dung | Key |
|------------|----------|-----|
| `grading_deco` / `grading_searchpie` | Kết quả chấm điểm QA theo app | `(session_id, date)` |
| `sumtag_deco` / `sumtag_searchpie` | Summary + tags theo segment | `(session_id, date)` |
| `qa_reviews` | Review Performance (đánh giá agent thủ công) | — |
| `qa_users` | Tài khoản Dashboard (email, role) | `email` |
| `crawl_stats` | Số liệu Crisp thật (đối soát với số đã chấm) | `(date, website_id)` |
| `deco_docs` / `searchpie_docs` | Markdown gốc knowledge base cho RAG | — |
| `prompts` | Lịch sử version prompt chấm điểm | `version` |

### 5.2. Đổi model LLM

Chỉ cần sửa **một dòng duy nhất** trong `.env`, áp dụng cho toàn bộ hệ thống (chấm điểm, tóm tắt, Agent Summarize):

```env
OPENROUTER_MODEL=deepseek/deepseek-v4-flash
```

Restart lại process đang chạy (`grading/scheduler.py`, `grading/main.py`, hoặc dashboard) để áp dụng model mới.

### 5.3. Review Performance — logic tính điểm cần nhớ

- "Tổng reviews" chỉ tính review có `cs1` (không tính review chỉ có `mentioned`/`cs2`/`tech`).
- Loại trừ review có `package = "Upgrade"` khỏi thống kê.
- App có 3 lựa chọn: `SearchPie`, `DECO`, `PAI` (PAI chỉ tồn tại trong domain `qa_reviews`, KHÔNG áp dụng cho chấm điểm/Analytics).

### 5.4. Đối soát số liệu Crisp thật

Analytics có tile "Tổng thật (Crisp)" lấy từ `crawl_stats` để so với số chat đã chấm — chênh lệch là do hệ thống chấm điểm chủ động lọc bỏ chat quá ngắn/không hợp lệ trước khi chấm, không phải lỗi thiếu dữ liệu. Chạy `scripts/backfill_crawl_stats.py` để cập nhật lại số liệu này khi cần.

### 5.5. MCP Server (kết nối Claude.ai)

```bash
python -m mcp_server.server --http
# hoặc: ./mcp_server/start_http.sh --port 8765
```

Quản lý email được phép dùng MCP connector:

```bash
python -m mcp_server.server --add-email new@example.com
python -m mcp_server.server --remove-email old@example.com
python -m mcp_server.server --list-emails
```

Copy URL in ra (`https://.../mcp`) vào **claude.ai → Settings → Integrations → Add MCP Server**.

| Tool | Công dụng |
|------|-----------|
| `qa_overview` | Tổng quan điểm theo khoảng ngày + LLM summary |
| `qa_by_date` | Chi tiết từng chat trong ngày |
| `qa_by_agent` | Điểm và phân tích theo agent |
| `qa_regrade` | Chấm lại 1 chat với prompt tuỳ chọn |
| `qa_prompt_get` / `qa_prompt_update` / `qa_prompt_suggest` | Quản lý version prompt chấm điểm |
