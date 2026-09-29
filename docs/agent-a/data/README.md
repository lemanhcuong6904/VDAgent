# Data Agent

Agent thực thi các bước dữ liệu trong execution plan của Orchestrator. Đây là agent duy nhất
được đọc Data Warehouse.

- Code: `src/agents/data/`
- Nhánh: `feature/data_agent` (code), `feature/data_test` (fixture, golden set, eval)

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| [spec.md](spec.md) | Đặc tả triển khai, contract tạm, task và gate G0–G6 | Draft, chờ chốt G0 |
| [design.md](design.md) | Thiết kế nghiệp vụ, kiến trúc, harness, đánh giá (chuyển từ PDF "[Đặc tả] Data Agent", v4) | Chuyển từ PDF ngày 29/09/2026 |
