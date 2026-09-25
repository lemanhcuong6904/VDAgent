# Tài liệu VDaAgent / Team 6 cAi

Tài liệu này mô tả code hiện có và các contract để mở rộng repository. README ở thư mục gốc là
hướng dẫn bắt đầu nhanh; trang này giúp tìm tài liệu theo công việc.

## Chọn hướng dẫn

- Khởi động nhanh, cấu hình môi trường và lệnh kiểm tra: [README](../README.md).
- Luồng dữ liệu, memory, sandbox, scale và deploy: [Kiến trúc](architecture.md).
- Tạo agent plugin, prompt, guardrail, input/output schema và đăng ký roster: [Agent guide](agents.md).
- Viết MCP tool, đăng ký tool pool và cấp quyền cho từng agent: [MCP tool guide](tools.md).
- Gọi HTTP/MCP API, headers, payload, event và lỗi: [API reference](api.md).
- Quyền sở hữu file và phân chia vùng làm việc: [Folder ownership](folder-ownership.md).
- Liên kết developer API cũ: [Developer API](developer-api.md).

## Mô hình đăng ký hiện tại

Agent plugin và tool pool được lắp ráp lúc API khởi động từ `AGENT_PLUGIN_MODULES` và
`AGENT_TOOL_MODULES`. Đây là code TypeScript tin cậy được triển khai cùng server. Hiện không có
HTTP endpoint để upload module, tạo agent/tool động hoặc sửa quyền pool. `GET /v1/agents` và
`GET /v1/tools` chỉ đọc registry; `POST /v1/agents/{id}/run` gọi một agent đã đăng ký. Không gửi
source code hoặc credential provider từ model/browser.

Kiến trúc là modular monolith: một API process lắp ráp sáu agent mặc định và tool pool; PostgreSQL
lưu task, invocation, chat, Pi session, memory và artifact; Docker chạy sandbox. Xem
[architecture](architecture.md) để phân biệt khả năng hiện có với hướng nâng cấp scale.

## Chạy local

1. Cài Node.js 22 trở lên, Corepack, Docker Engine/Desktop và Docker Compose.
2. Cài dependencies bằng `corepack pnpm install --frozen-lockfile` và
   `npm --prefix frontend ci`.
3. Sao chép `.env.example` thành `.env`; đặt token local, mật khẩu PostgreSQL và `MODEL_API_KEY`.
   `DATABASE_URL` trong Compose phải dùng cùng user/password với cấu hình PostgreSQL.
4. Chạy `docker compose up --build -d`; API phục vụ UI tại `http://localhost:3000`.
5. Xác minh `curl -fsS http://localhost:3000/health` trả `{"status":"ok"}`.

Không commit `.env` hoặc dùng dữ liệu thật trong test. `docker compose down` giữ named volume DB;
chỉ dùng `docker compose down -v` nếu chủ ý xóa dữ liệu local. Chi tiết và lệnh hot reload nằm ở
[README](../README.md).

## Kiểm thử

Chạy `corepack pnpm check`, `corepack pnpm lint`, `corepack pnpm test`,
`corepack pnpm frontend:build` và `npm --prefix frontend test`. Test mặc định không gọi model/warehouse
thật. PostgreSQL integration tests gồm memory isolation, Pi session locking và analytics E2E; chúng
chỉ chạy khi `TEST_DATABASE_URL` trỏ tới database test dùng riêng. Nếu biến này không có, Vitest sẽ
skip các integration test đó. Không trỏ biến test tới production hoặc database có dữ liệu cần giữ.

Xem [folder ownership](folder-ownership.md) để biết team nào cập nhật contract, code và test tương
ứng. Quyền push/PR theo nhánh được quy định riêng ở [`GIT_RULE.md`](../GIT_RULE.md).
