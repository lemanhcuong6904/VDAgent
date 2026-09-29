# Tài liệu team AGENT_A

> **Lưu ý (2026-09-30):** phần lớn tài liệu trong thư mục này ban đầu mô tả một kiến trúc
> TypeScript (`src/agents/*.ts`, `analytics.ts`) chưa từng tồn tại trong repo. Theo
> [`docs/refactor/PLAN.md`](../refactor/PLAN.md) (quyết định của chủ dự án, 2026-09-29), bộ tài
> liệu này **không phải nguồn sự thật cho hành vi code** — nguồn sự thật là
> [`docs/superpowers/specs/*.md`](../superpowers/specs/). `design.md` của cả 3 agent trong thư
> mục này đã được viết lại (2026-09-30) để mô tả đúng kiến trúc Python/MCP hiện tại, nhưng nếu có
> mâu thuẫn với `docs/superpowers/specs/`, ưu tiên `docs/superpowers/specs/`.

Team AGENT_A sở hữu ba agent: **Orchestrator**, **Data** và **Report**. Thư mục này chứa toàn bộ
quy trình, contract và đặc tả của team. Tài liệu chung của repository (API, architecture, agent
guide) vẫn nằm ở [`docs/`](../README.md).

## Cấu trúc

```text
docs/agent-a/
├── README.md            # Trang này: mục lục và thứ tự đọc
├── workflow.md          # Nhánh, task, gate, PR, định nghĩa "xong"
├── contracts.md         # Contract chung Orchestrator ↔ Data ↔ Report
├── testing.md           # Fixture, golden set, eval E1–E8
├── orchestrator/
│   ├── README.md
│   ├── design.md          # Kiến trúc v4 hiện hành (2026-09-30)
│   └── contract-v1.0.md   # Giao thức cũ (agents.delegate) — lỗi thời, chỉ tham khảo lịch sử
├── data/
│   ├── README.md
│   └── design.md           # Kiến trúc LiteLLM+MCP hiện hành (2026-09-30)
└── report/
    ├── README.md
    ├── design.md           # Kiến trúc LangGraph + Jev judge hiện hành (2026-09-30)
    └── task-contract-v0.1.md  # Draft cũ — cần Orchestrator/Data xác nhận lại
```

Mỗi agent có hai loại tài liệu:

- **`design.md`** trả lời *làm gì và vì sao*: nghiệp vụ, kiến trúc, nghiên cứu tham khảo, đánh giá.
- **`spec.md`** trả lời *làm thế nào trong repo này*: vị trí code, contract, phụ thuộc, task và
  gate. Thành viên code theo `spec.md`.

## Trạng thái

| Tài liệu | Trạng thái |
| --- | --- |
| [workflow.md](workflow.md) | Draft |
| contracts.md | Chưa có. `data/spec.md` đã bị xóa khỏi repo trong refactor 2026-09-29, không còn bản tạm để dùng thay |
| testing.md | Chưa có |
| [orchestrator/design.md](orchestrator/design.md) | Viết mới 2026-09-30, khớp code |
| [orchestrator/contract-v1.0.md](orchestrator/contract-v1.0.md) | Lỗi thời — mô tả giao thức `agents.delegate` cũ, code thật dùng `send_to_agent` |
| [data/design.md](data/design.md) | Viết lại 2026-09-30, khớp code |
| [report/design.md](report/design.md) | Viết mới 2026-09-30, khớp code |
| [report/task-contract-v0.1.md](report/task-contract-v0.1.md) | Draft cũ, chưa xác nhận còn khớp code hiện tại hay không |

## Thứ tự đọc cho thành viên mới

1. [workflow.md](workflow.md): cách nhận task, dùng nhánh và mở PR.
2. [`docs/refactor/PLAN.md`](../refactor/PLAN.md) và [`docs/superpowers/specs/`](../superpowers/specs/):
   nguồn sự thật cho kiến trúc thật của repo — đọc trước khi tin bất kỳ chi tiết kỹ thuật nào
   trong `docs/agent-a/`.
3. `design.md` của agent mình phụ trách (data/orchestrator/report) để hiểu kiến trúc hiện hành.
4. [Agent guide](../agents.md) và [MCP tool guide](../tools.md) của repository.

## Quy tắc

- Tài liệu của team chỉ nằm trong thư mục này. Không tạo `docs/agent-a-*.md` ở cấp `docs/`.
- Code đổi hành vi hoặc contract thì tài liệu tương ứng đổi trong cùng PR.
- `contracts.md` và `workflow.md` chỉ thay đổi khi có lead duyệt.
