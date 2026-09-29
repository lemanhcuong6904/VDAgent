# Report Agent

Agent viết report từ kết quả Compare, Insight và Visualize, trích dẫn artifact ID và chỉ lưu
report khi người dùng yêu cầu.

- Code: `src/agents/report/`, fallback report trong `src/agents/analytics.ts`
- Nhánh: `feature/report_agent`

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| design.md | Thiết kế nghiệp vụ và kiến trúc | Chờ tài liệu thiết kế |
| spec.md | Đặc tả triển khai, task và gate | Chưa có |
| [task-contract-v0.1.md](task-contract-v0.1.md) | Draft contract Orchestrator → Report (ReportStepSpec, upstream_status, checklist cần Oces xác nhận); chuyển từ PDF "VDAgent_Orchestrator_to_Report_TaskContract_v0.1.docx" | Chuyển từ PDF ngày 29/09/2026 |

Trong lúc chờ: task `R-40` (đọc manifest của Data Package) đã nằm trong
[data/spec.md](../data/spec.md) mục 5.
