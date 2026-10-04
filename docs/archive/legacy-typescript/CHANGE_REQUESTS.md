# Change requests

Thay đổi public contract/tên file được ghi ở đây; CR-0006 đổi tên file schema (không đổi `$id` trên wire).

| ID | Scope | Decision | Status |
| --- | --- | --- | --- |
| CR-0001 | M0.3/M0.4 execution receipt và schema toolchain | [ADR 0001](decisions/0001-schema-and-receipt-toolchain.md) | Implemented locally, human review pending |
| CR-0002 | M0 inventory, legacy import debt, dependency/toolchain pinning | [ADR 0002](decisions/0002-baseline-boundaries-and-dependencies.md) | Implemented locally, gates pending |
| CR-0003 | M1 public wire contracts and generated declarations | [ADR 0003](decisions/0003-public-contracts.md) | In progress; legacy runtime unchanged |
| CR-0004 | Reconcile canonical contracts, isolate draft adapters, restore durable ledger | [ADR 0004](decisions/0004-reconcile-contract-prototypes.md) | Implemented locally; human review pending |

Thay đổi contract phải có decision tại `docs/decisions/` ghi requirement, schema/version,
consumers, migration, compatibility, tests, trade-off và rollback trước khi triển khai.
`baseline.v1` cũ chỉ là historical capture. Capture mới dùng schema `execution.v1`;
validator không tự nâng bằng chứng cũ thành receipt đã kiểm chứng.

CR-0005: [Port call/result wire v1](decisions/0005-port-wire-contracts.md), additive
M1 schema/type/testkit work. Production protocols unchanged; implementation in progress.
| CR-0006 | Owner-directed cleanup: một phiên bản duy nhất cho mỗi file | Owner yêu cầu 2026-09-27: xóa bản cũ, thay bằng bản mới; không đặt version trong tên file. `versions.json` giữ version; schema/generated/evidence bỏ hậu tố `.v1`/`.v2`; receipt FAIL/BLOCKED đã có bản PASS thì xóa. Ghi đè PLAN §15.3 (giữ compatibility path) theo quyết định owner. Backup tạm: `$CLAUDE_JOB_DIR/tmp/pre-rename-backup.tar.gz`. | APPLIED |
