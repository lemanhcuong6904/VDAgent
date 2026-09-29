# Tài liệu team AGENT_A

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
│   ├── design.md        # Thiết kế nghiệp vụ và kiến trúc
│   └── spec.md          # Đặc tả triển khai + task/gate
├── data/
│   ├── README.md
│   ├── design.md
│   └── spec.md
└── report/
    ├── README.md
    ├── design.md
    └── spec.md
```

Mỗi agent có hai loại tài liệu:

- **`design.md`** trả lời *làm gì và vì sao*: nghiệp vụ, kiến trúc, nghiên cứu tham khảo, đánh giá.
- **`spec.md`** trả lời *làm thế nào trong repo này*: vị trí code, contract, phụ thuộc, task và
  gate. Thành viên code theo `spec.md`.

## Trạng thái

| Tài liệu | Trạng thái |
| --- | --- |
| [workflow.md](workflow.md) | Draft |
| contracts.md | Chưa có. Tạm dùng mục 3 của [data/spec.md](data/spec.md) |
| testing.md | Chưa có |
| [orchestrator/](orchestrator/README.md) | Chờ tài liệu thiết kế |
| [data/spec.md](data/spec.md) | Draft, chờ chốt Gate G0 |
| data/design.md | Chưa đưa vào repo (bản "Thiết kế sơ bộ Data Agent v01") |
| [report/](report/README.md) | Chờ tài liệu thiết kế |

## Thứ tự đọc cho thành viên mới

1. [workflow.md](workflow.md): cách nhận task, dùng nhánh và mở PR.
2. `contracts.md` (hoặc mục 3 của [data/spec.md](data/spec.md) khi chưa có): các agent nói
   chuyện với nhau thế nào.
3. `spec.md` của agent mình phụ trách, rồi `design.md` của agent đó để hiểu lý do.
4. [Agent guide](../agents.md) và [MCP tool guide](../tools.md) của repository.

## Quy tắc

- Tài liệu của team chỉ nằm trong thư mục này. Không tạo `docs/agent-a-*.md` ở cấp `docs/`.
- Code đổi hành vi hoặc contract thì tài liệu tương ứng đổi trong cùng PR.
- `contracts.md` và `workflow.md` chỉ thay đổi khi có lead duyệt.
