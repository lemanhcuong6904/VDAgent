# Tài liệu VDaAgent / Team 6 cAi

Tài liệu này mô tả code đang có trong repository và cách mở rộng qua contract hiện hành.

## Bắt đầu theo công việc

- Muốn hiểu các thành phần và luồng xử lý: [Kiến trúc](architecture.md).
- Muốn viết agent mới, khai báo prompt, schema và tools: [Agent](agents.md).
- Muốn viết MCP tool, đăng ký vào pool và cấp tool cho agent: [MCP tool](tools.md).
- Muốn gọi các endpoint, biết header, body và lỗi: [HTTP/MCP API](api.md).
- Muốn biết file nào thuộc team nào và nơi đặt thay đổi mới: [Folder ownership](folder-ownership.md).

## Trạng thái đăng ký

Agent plugin và tool pool hiện được lắp ráp lúc khởi động từ `AGENT_PLUGIN_MODULES` và
`AGENT_TOOL_MODULES`. Đây là API nội bộ dành cho developer triển khai module trên server. Hiện
không có endpoint CRUD để upload module, tạo agent động, tạo tool động hoặc thay quyền pool qua
HTTP. Endpoint `GET /v1/agents` và `GET /v1/tools` là endpoint đọc; `POST /v1/agents/{id}/run`
thực thi agent đã đăng ký. Không gửi mã module hoặc credential provider từ model/browser.

Kiến trúc hiện tại là modular monolith: một API process lắp ráp các agent/tool plugin; PostgreSQL
lưu session, memory, task và artifact; Docker cung cấp sandbox. Xem [kiến trúc](architecture.md)
để biết khi nào cần cân nhắc worker hoặc service riêng.

## Cài và chạy local

1. Cài backend bằng `corepack pnpm install --frozen-lockfile` và frontend bằng
   `npm --prefix frontend ci`.
2. Sao chép `.env.example` thành `.env`, sau đó đặt `API_TOKEN`, mật khẩu PostgreSQL và
   `MODEL_API_KEY` trong file local. Không commit `.env` hoặc đưa giá trị bí mật vào tài liệu,
   log hay ví dụ.
3. Chạy `docker compose up --build`. API phục vụ frontend tại `http://localhost:3000`.
4. Xác minh `GET /health` trả `{ "status": "ok"}`. Ví dụ gọi API developer dùng `curl` trong
   [API reference](api.md).

Các lệnh kiểm tra và quy ước đặt file ở [folder ownership](folder-ownership.md).
