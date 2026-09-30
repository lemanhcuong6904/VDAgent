# Report Agent

Agent viết report (markdown + chart) từ kết quả các agent khác, trích dẫn artifact ID.

- Code hiện tại: `agents/report/vdagent_report/` — package Python, LangGraph +
  Jev quality gate (xem [design.md](design.md)). **Không còn** ở `src/agents/report/`
  (TypeScript) như ghi trước đây; kiến trúc `src/agents/analytics.ts` (fallback report,
  `createFallbackReport`, `extractSpecialistResult`) không áp dụng cho code Python này.
- Nhánh: `feature/report_agent`

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| [design.md](design.md) | Kiến trúc thật hiện hành: graph LangGraph, cơ chế Jev judge, tool MCP thật sự dùng, đọc trực tiếp từ code | Mới, khớp code ngày 30/09/2026 |
| spec.md | Đặc tả triển khai, task và gate | Chưa có |
| [task-contract-v0.1.md](task-contract-v0.1.md) | Draft contract Orchestrator → Report (ReportStepSpec, upstream_status); dựa trên kiến trúc TypeScript + semantic layer phía Data đã bị xóa trong refactor sang Python/MCP — **chưa xác nhận còn khớp code hiện tại hay không**, xem cảnh báo đầu file | Draft cũ, chuyển từ PDF ngày 29/09/2026 |

Đổi hành vi (prompt, luồng graph, tool manifest) → đọc `design.md` trước, và cập nhật nó cùng lúc
với code (đúng CODING_RULES.md: docs của team đổi theo hành vi thật).
