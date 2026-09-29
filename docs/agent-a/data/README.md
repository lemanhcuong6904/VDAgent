# Data Agent

Agent duy nhất có tool đọc trực tiếp Data Warehouse. Kiến trúc thật hiện tại là một vòng lặp
tool-calling mỏng qua LiteLLM + MCP (không còn pipeline tất định nhiều bước như bản thiết kế cũ —
xem mục 0 của `design.md`).

- Code: `agents/data/vdagent_data/` (Python plugin; `agent.py`, `llm.py`, `mcp_client.py`,
  `settings.py`, `prompts/system.md`, `prompts/compact.md`, `tests/test_agent.py`)
- Nhánh: `feature/data_agent` (code), `feature/data_test` (fixture, golden set, eval)

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| spec.md | Đặc tả triển khai, contract tạm, task và gate G0–G6 | Đã xóa khỏi repo trong lần refactor xóa kiến trúc pipeline cũ trên `main`; chưa có bản thay thế |
| [design.md](design.md) | Thiết kế kỹ thuật khớp code hiện tại (v5): tool-calling loop, MCP, nén hội thoại, cấu hình, test | Viết lại 30/09/2026 theo code thật; bản v4 (PDF, pipeline S0–S7) còn trong lịch sử Git của file này để tham khảo bối cảnh cũ |
