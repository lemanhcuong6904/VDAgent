# Orchestrator Agent

Agent hiểu câu hỏi, viết execution plan, giao bước cho các specialist qua `agents.delegate` và
tổng hợp câu trả lời cuối.

- Code: `src/agents/orchestrator/`, phần điều phối trong `src/agents/analytics.ts`
- Nhánh: `feature/orchestrator_agent`

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| design.md | Thiết kế nghiệp vụ và kiến trúc | Chờ tài liệu thiết kế |
| spec.md | Đặc tả triển khai, task và gate | Chưa có |
| [contract-v1.0.md](contract-v1.0.md) | Contract giao tiếp Orchestrator ↔ 5 agent (9 message, 3 phản hồi, header chung, tab riêng từng agent, ví dụ JSON); chuyển từ PDF "Orchestrator- Function Agent Contract" | Chuyển từ PDF ngày 29/09/2026 — có thể cần dời lên `docs/agent-a/contracts.md` theo cấu trúc trong README gốc |

Trong lúc chờ: các task `O-` liên quan tới Data Agent đã nằm trong
[data/spec.md](../data/spec.md) mục 5.
