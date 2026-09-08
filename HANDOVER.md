# Checklist chuyển giao dự án

Danh sách những gì cần **kiểm tra / đổi chủ sở hữu / rotate** khi bàn giao Support Analyzer cho người hoặc team khác. Không liệt kê giá trị secret thật — chỉ nói cái gì cần đổi và đổi ở đâu.

> Nguyên tắc chung: bất kỳ credential nào **gắn với tài khoản cá nhân của người bàn giao** (Google account, SSH key, API key cá nhân) đều nên **rotate/tạo mới** thay vì tiếp tục dùng chung — để khi thu hồi quyền của người cũ, hệ thống không bị chết theo.

---

## 1. Google OAuth (đăng nhập Dashboard + MCP connector)

- **Ở đâu**: `.env` → `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`. Tạo tại [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials.
- **Vấn đề khi bàn giao**: OAuth Client này thuộc về một **Google Cloud project** — nếu project đó do người cũ sở hữu và họ rời đi/bị revoke, cả hệ thống login sẽ chết ngay lập tức.
- **Cần làm**:
  - [ ] Xác nhận ai là **Owner** của GCP project đang chứa OAuth Client này (Google Cloud Console → IAM & Admin → IAM).
  - [ ] Thêm chủ mới làm Owner/Editor của project, hoặc tạo OAuth Client mới trong project do chủ mới kiểm soát.
  - [ ] Nếu tạo Client mới: cập nhật `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` trong `.env`, và thêm đúng `Authorized redirect URIs` (`<domain>/api/auth/callback`) trong Console.
  - [ ] Cập nhật `ADMIN_EMAILS` trong `.env` — hiện đang trỏ về email cá nhân của người bàn giao, cần đổi sang email admin mới (xem mục 6).

## 2. Crisp API

- **Ở đâu**: `.env` → `CRISP_IDENTIFIER`, `CRISP_KEY`. Tạo/xem tại Crisp Dashboard → Settings → Plugins (hoặc Marketplace → API tokens), thuộc workspace Crisp của PieLab.
- **Vấn đề khi bàn giao**: token này thuộc **workspace** (không phải cá nhân) nên thường vẫn sống khi đổi người quản lý — nhưng cần xác nhận ai còn quyền **Owner/Admin** của workspace Crisp để có thể tạo token mới nếu token cũ bị revoke.
- **Cần làm**:
  - [ ] Xác nhận người mới có quyền Owner/Admin trên Crisp workspace (Settings → Team Members).
  - [ ] Nếu người bàn giao là Owner duy nhất — chuyển quyền Owner hoặc thêm người mới làm Admin trước khi họ rời đi.
  - [ ] `WEBSITE_ID` hardcode trong `scripts/backfill_shop_domain.py` (`17e47fa7-...`) — chỉ cần đổi nếu chuyển sang workspace/website Crisp khác.

## 3. MongoDB + SSH Tunnel

- **Ở đâu**: `.env` → `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_AUTH_SOURCE`, `MONGO_DB` (kết nối DB) và `SSH_TUNNEL_HOST`, `SSH_TUNNEL_USER`, `SSH_TUNNEL_KEY` (SSH tới bastion để mở tunnel).
- **Vấn đề khi bàn giao — mục nhạy cảm nhất**: `SSH_TUNNEL_KEY` hiện trỏ tới **private key cá nhân** của người bàn giao (`/home/<user>/.ssh/id_ed25519`). Không thể "chuyển" private key này cho người khác dùng chung — mỗi người nên có key riêng.
- **Cần làm**:
  - [ ] Người mới tạo cặp SSH key riêng, gửi **public key** cho người quản lý bastion host (`SSH_TUNNEL_HOST`) để thêm vào `authorized_keys`.
  - [ ] Cập nhật `SSH_TUNNEL_KEY` trong `.env` của người mới trỏ tới key riêng của họ.
  - [ ] Sau khi bàn giao xong, **thu hồi quyền SSH** (xóa public key khỏi `authorized_keys`) của người cũ trên bastion host.
  - [ ] Cân nhắc **đổi `MONGO_PASSWORD`** sau khi bàn giao nếu người cũ không còn cần quyền truy cập — nhớ cập nhật lại `.env` mọi nơi đang deploy (server + máy dev mới) nếu đổi.

## 4. OpenRouter (LLM)

- **Ở đâu**: `.env` → `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`. Tài khoản tại [openrouter.ai](https://openrouter.ai).
- **Vấn đề khi bàn giao**: key này gắn với **billing** của tài khoản OpenRouter — nếu tài khoản là của cá nhân người bàn giao, họ vẫn đang trả tiền cho toàn bộ hệ thống chấm điểm cho tới khi đổi.
- **Cần làm**:
  - [ ] Xác nhận tài khoản OpenRouter đang dùng là tài khoản công ty/team hay cá nhân.
  - [ ] Nếu cá nhân: tạo tài khoản OpenRouter mới (công ty), tạo API key mới, cập nhật `OPENROUTER_API_KEY` trong `.env`, revoke key cũ sau khi xác nhận hệ thống mới chạy ổn.

## 5. JWT Dashboard Auth

- **Ở đâu**: `.env` → `JWT_SECRET`.
- **Cần làm**:
  - [ ] **Luôn đổi `JWT_SECRET` sang giá trị mới** khi bàn giao (invalidate toàn bộ session cookie cũ, tránh người cũ tự forge token nếu từng biết secret).
  - [ ] Sau khi đổi, mọi người dùng dashboard phải đăng nhập lại.

## 6. Quyền truy cập Dashboard & MCP connector

- **Ở đâu**: MongoDB collection `qa_users` (quản lý qua tab **User Management** trên UI, hoặc trực tiếp DB) và `auth_emails` (MCP connector, quản lý qua `python -m mcp_server.server --list-emails` / `--add-email` / `--remove-email`).
- **Cần làm**:
  - [ ] Rà lại danh sách `qa_users` — xóa/hạ quyền tài khoản của người rời đi, thêm admin mới.
  - [ ] Rà lại `auth_emails` (MCP) tương tự bằng `--list-emails`, xóa email không còn cần quyền.
  - [ ] Cập nhật `ADMIN_EMAILS` trong `.env` (mục 1) để lần đăng nhập đầu tiên của người mới tự động lên `admin`.

## 7. Domain / Server / Hosting

- **Ở đâu**: `.env` → `BACKEND_URL`, `FRONTEND_URL`; server chạy `start_ui.sh --prod` (xem `OPERATIONS.md` §4).
- **Cần làm**:
  - [ ] Xác nhận ai đứng tên domain (registrar) và hosting/VPS đang chạy server — chuyển ownership hoặc chuyển billing nếu cần.
  - [ ] Thêm SSH key của người mới vào server (khác với SSH key tới MongoDB bastion ở mục 3 — đây là server chạy dashboard).
  - [ ] Thu hồi SSH access của người cũ trên server sau khi bàn giao xong.

## 8. MCP Server public URL

- **Ở đâu**: `.env` → `PUBLIC_URL` (nếu dùng ngrok: tài khoản ngrok riêng, `ngrok config add-authtoken`).
- **Cần làm**:
  - [ ] Nếu dùng ngrok với tài khoản cá nhân của người bàn giao — người mới cần tài khoản ngrok riêng (ngrok free chỉ có 1 static domain/tài khoản) và authtoken riêng.
  - [ ] Nếu dùng domain thật (không ngrok) — không cần đổi, chỉ cần đảm bảo domain vẫn thuộc quyền kiểm soát của team (xem mục 7).

## 9. Git repository

- **Cần làm**:
  - [ ] Chuyển ownership repo (GitHub/GitLab org) hoặc thêm người mới làm collaborator/admin.
  - [ ] Rà lại danh sách collaborator, gỡ quyền người rời đi sau khi bàn giao xong.

## 10. File nhạy cảm — KHÔNG nằm trong git, phải chuyển thủ công

Các file này bị `.gitignore` chặn (xem `.gitignore` gốc repo) nên `git clone` không mang theo — phải gửi qua kênh an toàn (password manager / encrypted share), không paste vào chat thường:

- [ ] `.env` (toàn bộ secrets: Crisp, OpenRouter, Mongo, OAuth, JWT)
- [ ] SSH private key dùng cho `SSH_TUNNEL_KEY` (khuyến khích tạo key mới thay vì chuyển key cũ — xem mục 3)

---

## Sau khi bàn giao xong

- [ ] Đổi `JWT_SECRET`, `MONGO_PASSWORD` (nếu cần), revoke SSH key cũ, gỡ quyền admin/collaborator cũ — **theo đúng thứ tự này** (đổi/thêm mới trước, xác nhận hệ thống mới chạy ổn, rồi mới thu hồi quyền cũ) để tránh tự khóa mình ra khỏi hệ thống giữa chừng.
