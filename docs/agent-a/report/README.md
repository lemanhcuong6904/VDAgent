# Report Agent

Agent viết report (markdown + chart) từ kết quả các agent khác, trích dẫn artifact ID.

- Code hiện tại: `agents/report/vdagent_report/` — package Python, LangGraph +
  Jev quality gate (xem [design.md](design.md)). **Không còn** ở `src/agents/report/`
  (TypeScript) như ghi trước đây; kiến trúc `src/agents/analytics.ts` (fallback report,
  `createFallbackReport`, `extractSpecialistResult`) không áp dụng cho code Python này.
- Nhánh: `feature/report_agent`

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| [design.md](design.md) | Kiến trúc thật hiện hành: graph LangGraph, cơ chế Jev judge, tool MCP thật sự dùng, đọc trực tiếp từ code | Đã cập nhật 30/09/2026, khớp code |
| [spec.md](spec.md) | Đặc tả triển khai chat riêng và Orchestrator, ranh giới tool, envelope AgentReport@1 | Nguồn sự thật cho code Report Agent (30/09/2026) |
| [task-contract-v0.1.md](task-contract-v0.1.md) | Draft contract cũ (ReportStepSpec) — lỗi thời, không dùng làm runtime contract | Draft cũ tham khảo |

Đổi hành vi (prompt, luồng graph, tool manifest) → đọc `design.md` trước, và cập nhật nó cùng lúc
với code (đúng CODING_RULES.md: docs của team đổi theo hành vi thật).
