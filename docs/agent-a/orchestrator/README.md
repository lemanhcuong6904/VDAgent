# Orchestrator Agent

Agent hiểu câu hỏi, viết execution plan, giao bước cho các specialist qua `send_to_agent` và
tổng hợp câu trả lời cuối.

- Code: `agents/orchestrator/vdagent_orchestrator/` (Python; xem `agents/orchestrator/README.md`
  cho hướng dẫn chạy/cấu hình)
- Cơ chế gọi specialist thật: `ctx.call_agent(...)` (tool `send_to_agent`), gửi một `StepSpec@1`
  JSON — **không phải** `agents.delegate`/TypeScript như phần mô tả cũ dưới đây từng nói. Chi tiết
  kiến trúc: [design.md](design.md).
- Nhánh: `feature/orchestrator_agent`

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| [design.md](design.md) | Thiết kế nghiệp vụ và kiến trúc v4 hiện hành, viết lại từ code thật (30/09/2026) | Khớp code |
| spec.md | Đặc tả triển khai, task và gate | Chưa có |
| [contract-v1.0.md](contract-v1.0.md) | Contract giao tiếp Orchestrator ↔ 5 agent (9 message, 3 phản hồi, header chung, tab riêng từng agent, ví dụ JSON); chuyển từ PDF "Orchestrator- Function Agent Contract" | **Lỗi thời — chờ viết lại.** Mô tả giao thức message cũ (`agents.delegate`, TypeScript); code hiện tại dùng `send_to_agent` + StepSpec/AgentReport (xem [design.md](design.md) mục 9 và 2). Không xoá — vẫn có phần khái niệm về ranh giới trách nhiệm còn dùng được, nhưng không nên tra cứu để biết định dạng message thật. |

Trong lúc chờ: các task `O-` liên quan tới Data Agent đã nằm trong
[data/spec.md](../data/spec.md) mục 5.
