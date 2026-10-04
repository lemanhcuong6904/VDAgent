# Archive

Bản ghi lịch sử và kiểm toán của VDaAgent. **Nội dung trong archive chỉ mang tính lịch sử**: không mô tả hệ thống hiện
tại và không được cập nhật để mô tả nó. Tài liệu chuẩn hiện hành nằm ngoài archive, xem [docs/README.md](../README.md).
Code và dữ liệu đã gỡ khỏi repo vẫn khôi phục được từ Git (commit `aed2917`).

| Mục | Nội dung | Thay bằng (hiện hành) |
|---|---|---|
| [`agents-history-2026-09.md`](agents-history-2026-09.md) | Nhật ký trạng thái cũ của `AGENTS.md` (§0–§26, 2026-09-30 → 2026-10-04) | [`AGENTS.md`](../../AGENTS.md) |
| [`legacy-typescript/`](legacy-typescript/) | Nền tảng TypeScript/PostgreSQL đã gỡ ở Phase 4: tài liệu API, kiến trúc, vận hành, contract, ADR (`decisions/`), runbook, quy trình team AGENT_A (`agent-a/workflow.md`), `PLAN.md`, `PROGRESS.md`, `CHANGE_REQUESTS.md` | [`architecture/system.md`](../architecture/system.md), [`GIT_RULE.md`](../../GIT_RULE.md) |
| [`integration-2026-09/`](integration-2026-09/) | Tích hợp sáu agent trên kho giả: kế hoạch WS1–WS7 (quyết định D1–D10), audit WS7, chuyển sang backend v2, runbook demo 4 happy case và các thư mục `*_evidence/` (log, JSON, ảnh) | [`architecture/decisions.md`](../architecture/decisions.md), [`testing/e2e-golden.md`](../testing/e2e-golden.md) |
| [`refactor-2026-09-29/`](refactor-2026-09-29/) | Kế hoạch, task và handoff của đợt refactor 2026-09-29 (đã hoàn tất) | backend v2, [`backend/README.md`](../../backend/README.md) |
| [`agent-contracts-legacy/`](agent-contracts-legacy/) | Giao thức Orchestrator ↔ agent v1.0 (9 message; Data vẫn có cửa v1.0 riêng, `wire.py`) kèm hình, và draft Report task contract v0.1 | [`contracts/agent-contract.md`](../contracts/agent-contract.md), [`agents/orchestrator.md`](../agents/orchestrator.md), [`agents/report.md`](../agents/report.md) |
| [`warehouse/`](warehouse/) | Bối cảnh tích hợp kho bằng pipeline CSV (đã retire ở Phase 2) | [`contracts/warehouse-v3.1.0.md`](../contracts/warehouse-v3.1.0.md), [`warehouse/backup/README.md`](../../warehouse/backup/README.md) |
| [`specs/`](specs/) | Đặc tả thiết kế có ngày 2026-09-24 → 2026-09-29 (`superpowers/`: hệ thống, template, plugin, agent freedom, tái cấu trúc backend) và `agent-design.html`; đã triển khai, code đã đi xa hơn | docstring `sdk/vdagent_sdk` (`make sdk-docs`), [`backend/README.md`](../../backend/README.md) |
| [`agent-a-assets/`](agent-a-assets/) | Hình của thiết kế Data agent cũ (pipeline S0–S7) | [`agents/data/README.md`](../../agents/data/README.md) |

Quy tắc:

- Archive chỉ là lịch sử. Không dẫn link từ tài liệu hiện hành vào archive để mô tả hành vi hiện tại.
- Tài liệu hết hiệu lực được chuyển vào đây bằng `git mv` (giữ lịch sử), kèm một dòng trong bảng trên.
- Không xóa bằng chứng kiểm toán (`*_evidence/`) nếu chưa chứng minh được là bản trùng không có giá trị riêng.
