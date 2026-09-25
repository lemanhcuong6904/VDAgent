# Tài liệu dành cho developer

Trang này được giữ làm đường dẫn tương thích cho liên kết cũ. Bắt đầu từ [mục lục tài liệu](README.md).

- [Tổng quan kiến trúc](architecture.md)
- [API HTTP và MCP](api.md)
- [Tạo và đăng ký agent](agents.md)
- [Tạo MCP tool và cấp quyền](tools.md)
- [Cấu trúc thư mục và quyền sở hữu](folder-ownership.md)

Agent và tool hiện là module TypeScript tin cậy, được nạp khi API khởi động. Không có HTTP API
để tạo hoặc đăng ký agent/tool vào runtime pool. Các API runtime được mô tả trong `api.md` chỉ
liệt kê và thực thi những module đã đăng ký.
