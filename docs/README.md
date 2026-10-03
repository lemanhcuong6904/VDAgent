# Documentation

Mục lục **duy nhất** của tài liệu VDaAgent / Team 6 cAi, dành cho engineer và owner agent. Hệ thống: web UI → Backend
FastAPI (6 agent là plugin cùng process) → DAG Orchestrator → Data → [Insight ∥ Compare] → Chart → Report, đọc kho
AWS RDS `cdw` (`re` → `gold`, `SNAP-20260630-01`, `3.1.0`). Kho giả SQLite chỉ dùng khi chỉ định rõ.

## Start Here

- [README Quick Start](../README.md): cài đặt, `make up`, biến môi trường, xử lý lỗi.
- [Architecture](architecture/system.md): kiến trúc multi-agent, luồng chạy, dữ liệu, giới hạn.
- [Decisions](architecture/decisions.md): quyết định D1–D10 đã duyệt và blocker đang mở.
- [AGENTS.md](../AGENTS.md): quy tắc kỹ thuật bắt buộc và trạng thái kiểm chứng mới nhất.

## Contracts

- [Data contract](contracts/data-contract.md): envelope artifact, payload, `report@1`, ánh xạ trường.
- [Agent contract](contracts/agent-contract.md): operation, đầu vào/ra, mã lỗi từng agent.
- [Warehouse contract v3.1.0](contracts/warehouse-v3.1.0.md): schema `gold` / lớp view `re`.

## Agent Design

- [Orchestrator](agents/orchestrator.md) (chạy/cấu hình: [`agents/orchestrator/README.md`](../agents/orchestrator/README.md))
- [Data](../agents/data/README.md)
- [Report](agents/report.md)
- Insight, Compare, Chart: [`agents/insight/README.md`](../agents/insight/README.md) và
  [`AGENT.md`](../agents/insight/AGENT.md), [`agents/compare/README.md`](../agents/compare/README.md),
  [`agents/chart/README.md`](../agents/chart/README.md).
- Backend (package map, luồng, MCP tools, Alembic): [`backend/README.md`](../backend/README.md). Hợp đồng plugin/SDK là
  docstring của `sdk/vdagent_sdk` (`make sdk-docs`).
- Team AGENT_A sở hữu Orchestrator, Data và Report.

## Testing

- [E2E / golden / acceptance](testing/e2e-golden.md): golden kho giả (A12-08) và AWS (`MAS-U03832`), `acceptance/ws7/run.sh`.
- Trước khi đẩy code: `uv run pytest -q -p no:cacheprovider`, `make docker-test`,
  `cd frontend && npm test && npm run build`, `make secret-check`.

## Security

- [Auth design](security/auth-design.md): F-05, `X-User-Id` chỉ dùng cho dev; chưa sẵn sàng production.
- Quét secret: `make secret-check`. Quy tắc Git và dữ liệu kho: [`GIT_RULE.md`](../GIT_RULE.md) (§9, §9.1).

## Frontend

- [Extension template](frontend/extension-template.md): thêm agent, API hoặc dữ liệu ở frontend.

## Product

- [`product/`](product/): `PRD_VDAgent.docx`, `VDAgent_Quy_dinh_Output_6_Agent.docx` và hai báo cáo mẫu (chỉ tham khảo
  cách trình bày, số liệu là minh họa).
- `product/VDAgent_API_Contract_FE_v0.3_OpenAPI.docx.pdf`: **bản nháp** API cho frontend (`/api/v1/...`, review, PDF),
  **chưa triển khai** và không phải API hiện tại (API hiện tại: [`backend/README.md`](../backend/README.md)); chờ owner
  FE/sản phẩm quyết định giữ làm mục tiêu hay lưu trữ.

## Data Recovery

- DR kho: [`warehouse/backup/README.md`](../warehouse/backup/README.md) (`cdw_gold_snapshot_20260630.dump`).
- Dữ liệu đã gỡ khỏi repo và cách khôi phục: [`data-archive/phase3-manifest.json`](data-archive/phase3-manifest.json).

## Historical Archive

[`archive/`](archive/README.md): nền tảng TypeScript cũ, tích hợp 2026-09-30 (kèm bằng chứng), kế hoạch refactor,
contract agent cũ, đặc tả thiết kế đã triển khai, lịch sử `AGENTS.md`. Tài liệu trong archive là bản ghi lịch sử/kiểm
toán, **không phải nguồn sự thật hiện tại**.

## Ownership and source of truth

| Nơi | Sở hữu |
|---|---|
| `README.md` | onboarding, Quick Start, lệnh `make`, biến môi trường |
| `docs/README.md` | mục lục tài liệu (trang này) |
| `AGENTS.md` | quy tắc kỹ thuật bắt buộc và trạng thái kiểm chứng hiện hành |
| `docs/architecture/*` | kiến trúc bền vững và quyết định |
| `docs/contracts/*` (3 file ở mục Contracts) | giao diện, hợp đồng dữ liệu và agent |
| `docs/agents/*`, `agents/*/README.md` | thiết kế và hướng dẫn chạy riêng từng agent |
| `docs/testing/*`, `docs/security/*`, `docs/frontend/*` | golden/acceptance, xác thực, mở rộng frontend |
| `docs/archive/*` | chỉ lịch sử và kiểm toán; không cập nhật để mô tả hệ thống hiện tại |

- Code và test thắng tài liệu; đổi hành vi thì sửa tài liệu chuẩn trong cùng PR.
- Mỗi chủ đề có một tài liệu chuẩn; nơi khác chỉ tóm tắt ngắn và dẫn link, không chép lại.
- Hợp đồng chung (`docs/contracts/`, catalog trong `contracts/`) đổi khi Integration Owner duyệt.
- Tài liệu mới thêm vào mục lục này; tài liệu hết hiệu lực chuyển vào `docs/archive/` (giữ banner, cập nhật `archive/README.md`).
- Không ghi secret vào tài liệu, chỉ ghi tên biến.
