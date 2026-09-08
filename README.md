# Support Analyzer

Hệ thống QA tự động chấm điểm hội thoại support của PieLab (DECO & SearchPie) từ Crisp, lưu vào MongoDB.

> Xem `OPERATIONS.md` để biết cách chạy QA Dashboard, deploy lên server, và vận hành/quản lý hệ thống (users, model LLM, MCP server, ...). File này chỉ liệt kê từng script và cách dùng.

---

## Cấu trúc thư mục (theo tính năng)

```
support_analyzer/
├── grading/          # Pipeline chấm điểm chính (chạy hàng ngày / thủ công)
│   ├── analyzer_v2.py        # Engine cốt lõi: fetch Crisp + chấm LLM
│   ├── main.py                # Chấm thủ công + lưu MongoDB
│   ├── scheduler.py           # Daemon tự động chấm 9h sáng mỗi ngày
│   ├── crawl.py                # Crawl Crisp về JSON thô
│   ├── build_references_from_db.py
│   ├── import_sumtag.py
│   ├── delete_range.py
│   ├── qa_references.json     # few-shot examples (sinh ra bởi build_references_from_db.py)
│   ├── data/                   # dữ liệu crawl lịch sử co-located
│   └── PIPELINE.md             # tài liệu kỹ thuật chi tiết analyzer_v2.py & scheduler.py
├── scripts/          # Công cụ bảo trì / migration / one-off (không chạy thường xuyên)
│   ├── migrate_collections.py
│   ├── backfill_shop_domain.py
│   ├── backfill_crawl_stats.py
│   ├── update_sumtag_app.py
│   └── diagnose_fetch.py
├── api/              # Backend QA Dashboard (FastAPI)
├── mcp_server/       # MCP connector cho Claude.ai
├── database/         # Data-access layer dùng chung (MongoDB, SSH tunnel)
├── docs/app_guides/  # RAG knowledge base (DECO Guidelines + SearchPie Docs)
├── ui/               # Frontend QA Dashboard (React), src/features/ chia theo tính năng
└── report/           # File JSON/Excel xuất ra từ các lần chấm điểm
```

Mọi script trong `grading/` và `scripts/` vẫn chạy trực tiếp bằng `python <đường dẫn>.py` như trước — chỉ đổi đường dẫn, cú pháp tham số (`--from`, `--to`, ...) không đổi. Luôn chạy từ thư mục gốc repo (nơi có `.env`, `report/`).

---

## Cài đặt

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Tạo file `.env` (xem mục [Biến môi trường](#biến-môi-trường)).

---

## Các file chính (`grading/`)

### `grading/scheduler.py` — Chấm điểm tự động hàng ngày

Chạy daemon, tự động chấm ngày hôm trước lúc **09:00 sáng giờ Việt Nam** mỗi ngày.

Quy trình mỗi ngày: fetch Crisp → chấm LLM (song song) → lưu MongoDB.

```bash
# Chạy daemon (chấm 9h sáng mỗi ngày)
python grading/scheduler.py

# Chấm ngay lập tức (ngày hôm qua)
python grading/scheduler.py --now

# Chấm ngày cụ thể rồi thoát
python grading/scheduler.py --date 2026-05-10
```

**Lưu vào:**
- MongoDB `grading_deco` / `grading_searchpie`
- MongoDB `sumtag_deco` / `sumtag_searchpie`
- File `qa_report_YYYYMMDD.json` (thư mục hiện tại)

---

### `grading/analyzer_v2.py` — Chấm điểm thủ công

Chấm thủ công theo ngày hoặc khoảng ngày, xuất ra file JSON local (không lưu MongoDB — dùng `main.py` nếu cần lưu DB).

```bash
# Chấm hôm nay
python grading/analyzer_v2.py

# Chấm ngày cụ thể
python grading/analyzer_v2.py --date 2026-05-10

# Chấm khoảng ngày
python grading/analyzer_v2.py --from 2026-05-01 --to 2026-05-10

# Chấm lại từ file JSON đã có (không fetch Crisp lại)
python grading/analyzer_v2.py --regrade ./report/qa_report_20260510.json
```

**Lưu vào:** File `./report/qa_report_YYYYMMDD.json`

---

### `grading/main.py` — Chấm thủ công + lưu MongoDB

Giống `analyzer_v2.py` nhưng **có lưu vào MongoDB**. Dùng để **chấm bổ sung** khi phát hiện thiếu dữ liệu ở ngày/khoảng ngày cụ thể.

```bash
python grading/main.py
python grading/main.py --date 2026-05-10
python grading/main.py --from 2026-05-01 --to 2026-05-10
python grading/main.py --regrade qa_report_20260510.json
python grading/main.py --no-mongo    # bỏ qua MongoDB, không cần tunnel
```

---

### `grading/crawl.py` — Crawl Crisp về JSON

Crawl dữ liệu hội thoại Crisp ra file JSON thô (không chấm điểm). Dùng để lấy dữ liệu lịch sử hoặc debug.

```bash
python grading/crawl.py --date 2026-05-10
python grading/crawl.py --from 2026-03-01 --to 2026-03-31
python grading/crawl.py --date 2026-05-10 --website <website_id>
```

---

### `grading/build_references_from_db.py` — Tạo few-shot examples

Đọc dữ liệu đã chấm từ MongoDB, chọn các ví dụ đại diện theo nhãn (perfect_10, solution_zero, ...) và tạo file `grading/qa_references.json` dùng cho few-shot prompting khi chấm.

Chạy lại mỗi khi muốn cập nhật ví dụ mẫu.

```bash
python grading/build_references_from_db.py
```

---

### `grading/import_sumtag.py` — Import sumtag từ JSON lịch sử

Import file JSON crawl lịch sử (`grading/data/`) vào collection sumtag, sau đó crawl catch-up đến hiện tại.

```bash
python grading/import_sumtag.py
python grading/import_sumtag.py --no-import          # chỉ catch-up, bỏ qua import JSON
python grading/import_sumtag.py --from 2026-04-01    # catch-up từ ngày cụ thể
```

---

### `grading/delete_range.py` — Xóa data trong khoảng ngày

Xóa dữ liệu trong khoảng ngày khỏi tất cả collection grading + sumtag. Luôn chạy `--dry-run` trước để xem thống kê trước khi xóa thật.

```bash
python grading/delete_range.py --from 2026-05-10 --to 2026-05-18 --dry-run
python grading/delete_range.py --from 2026-05-10 --to 2026-05-18
```

---

## Công cụ bảo trì (`scripts/`)

Các script one-off / migration, không chạy thường xuyên như pipeline trong `grading/`.

### `scripts/migrate_collections.py` — Migration dữ liệu cũ

Chuyển dữ liệu từ collections cũ (`deco_chat`, `sumtag`) sang collections mới chia theo app.

```bash
python scripts/migrate_collections.py            # chạy thật
python scripts/migrate_collections.py --dry-run  # chỉ xem thống kê, không ghi
```

### `scripts/backfill_shop_domain.py` — Backfill `shop_domain`

Backfill trường `shop_domain` cho các record grading/sumtag đã có, lấy từ Crisp conversation meta.

```bash
python scripts/backfill_shop_domain.py
```

### `scripts/backfill_crawl_stats.py` — Đối soát số liệu Crisp thật

Quét toàn bộ conversation Crisp một lượt (không chấm điểm), lưu tổng số thật vào `crawl_stats` để so sánh với số đã chấm (dùng cho tile "Tổng thật (Crisp)" trong Analytics).

```bash
python scripts/backfill_crawl_stats.py --from 2026-04-01 --to 2026-07-23
```

### `scripts/update_sumtag_app.py` — Backfill trường `app` cho sumtag

```bash
python scripts/update_sumtag_app.py
```

### `scripts/diagnose_fetch.py` — Diagnostic fetch theo ngày

Phân tích chi tiết từng bước drop khi fetch chat cho một ngày cụ thể (debug, không chấm điểm).

---

## `mcp_server/server.py` — MCP Server

Cung cấp tools cho Claude (MCP) để query dữ liệu QA và quản lý prompt. Xem `OPERATIONS.md` §5.5 để biết cách expose ra Internet (ngrok/domain) và quản lý email truy cập.

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

Xem `OPERATIONS.md` §5.1 cho danh sách đầy đủ collections (bao gồm `qa_reviews`, `qa_users`, `crawl_stats`, `deco_docs`/`searchpie_docs`).

---

## Biến môi trường

Tạo file `.env` ở thư mục gốc:

```env
# Crisp API
CRISP_IDENTIFIER=...
CRISP_KEY=...

# OpenRouter (LLM) — MỘT biến duy nhất cho toàn bộ model chat trong hệ thống
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=deepseek/deepseek-v4-flash

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

Xem `OPERATIONS.md` §2 cho các biến còn lại (OAuth, JWT, dashboard, MCP).
