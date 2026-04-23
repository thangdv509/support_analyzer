# Hướng dẫn vận hành Support Analyzer

## 1. Chuẩn bị (chỉ làm 1 lần)

```bash
cd /home/notta/Desktop/Code/Secomus/support_analyzer
source venv/bin/activate
```

Đảm bảo file `.env` có đủ các biến:
- `CRISP_IDENTIFIER`, `CRISP_KEY`
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`
- `MONGO_*`, `SSH_TUNNEL_*`
- `GOOGLE_SHEET_ID`, `GOOGLE_CREDENTIALS_PATH`

---

## 2. Chạy Auto-Grading (Scheduler)

### Chế độ chạy nền liên tục (khuyến nghị)

Tự động chấm ngày hôm trước lúc **9:00 sáng** mỗi ngày:

```bash
cd /home/notta/Desktop/Code/Secomus/support_analyzer
source venv/bin/activate
python scheduler.py
```

> Nếu khởi động sau 9h, sẽ chấm bổ sung ngày hôm qua ngay lập tức, rồi chờ đến 9h hôm sau.

Để chạy nền (không cần giữ terminal):

```bash
nohup python scheduler.py > scheduler.log 2>&1 &
echo "PID: $!"
```

Dừng:

```bash
kill <PID>
```

---

### Chấm thủ công

**Chấm ngày hôm qua ngay:**

```bash
python scheduler.py --now
```

**Chấm một ngày cụ thể rồi thoát:**

```bash
python scheduler.py --date 2026-04-22
```

---

### Kết quả mỗi lần chạy

| Output | Mô tả |
|--------|-------|
| `qa_report_YYYYMMDD.json` | File JSON local chứa toàn bộ kết quả |
| Google Sheet `"Support Analyzer"` | Append rows mới + tính lại avg theo agent |
| MongoDB `deco_chat` | Lưu session mới (skip session đã có) |
| `scheduler.log` | Log toàn bộ quá trình |

---

## 3. Chạy MCP Server

### Chế độ stdio — dùng với Claude Code CLI

Đã đăng ký sẵn, không cần chạy thêm. Claude Code sẽ tự khởi động khi cần.

Kiểm tra đăng ký:

```bash
claude mcp list
```

Đăng ký lại nếu cần:

```bash
claude mcp add --transport stdio qa-analyzer -- \
  /home/notta/Desktop/Code/Secomus/support_analyzer/venv/bin/python3 \
  -m mcp_server.server
```

---

### Chế độ HTTP — dùng với claude.ai web

Yêu cầu: **ngrok** đã cài và đã auth (`ngrok config add-authtoken <token>`).

```bash
cd /home/notta/Desktop/Code/Secomus/support_analyzer
chmod +x mcp_server/start_http.sh
./mcp_server/start_http.sh
```

Script sẽ in ra URL dạng:

```
✅ MCP Server sẵn sàng!
   URL: https://xxxx-xx-xx.ngrok-free.app/mcp
```

Vào **claude.ai → Settings → Integrations → Add MCP Server** và dán URL đó vào.

Dừng: `Ctrl+C`

---

### Các tool có trong MCP Server

| Tool | Mô tả |
|------|-------|
| `qa_overview` | Tổng quan điểm theo khoảng ngày + AI nhận xét |
| `qa_by_date` | Chi tiết từng chat trong một ngày |
| `qa_by_agent` | Điểm và phân tích theo agent |
| `qa_regrade` | Chấm lại một chat theo session_id |
| `qa_prompt_get` | Xem prompt QA đang active |
| `qa_prompt_update` | Cập nhật prompt mới vào DB |
| `qa_prompt_suggest` | AI gợi ý cải thiện prompt từ feedback |

---

## 4. Ghi chú quan trọng

- **Prompt chấm điểm** được lưu trong MongoDB (`prompts` collection). Muốn chỉnh sửa thì dùng tool `qa_prompt_update` thay vì sửa code.
- **SSH tunnel** tự động mở khi cần, tự đóng khi script thoát.
- **Google Sheets 503**: Script đã có retry tự động (5 lần, exponential backoff).
- Chấm lại TOÀN BỘ chat mỗi ngày; chỉ **bỏ qua khi lưu MongoDB** (không overwrite session đã có).
