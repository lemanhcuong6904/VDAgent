# Runbook: purge memory hoặc artifact theo yêu cầu xóa

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Khi dùng**: yêu cầu xóa dữ liệu của user/space, memory chứa PII
([pii-leak](pii-leak.md)), hoặc artifact sai phải thu hồi.

Thao tác này không đảo ngược được. Chỉ chạy khi có ticket được data owner duyệt, và chụp backup
trước ([backup-restore](backup-restore.md)).

## Memory (`agent_memory_entries`)

Agent tự xóa item của chính nó qua tool `memory.forget`; route này scope theo `(space, user, agent)`
(`src/postgres-store.ts`). Operator xóa theo user/space:

```sql
BEGIN;
SELECT count(*) FROM agent_memory_entries WHERE space_id = $1 AND user_id = $2;
DELETE FROM agent_memory_entries WHERE space_id = $1 AND user_id = $2;
-- Kiểm số dòng khớp với SELECT rồi mới COMMIT; nếu không khớp thì ROLLBACK.
COMMIT;
```

Dùng tham số, không nối chuỗi. Ghi ticket, số dòng và thời điểm vào audit; không ghi nội dung memory.

## Artifact (`artifacts`, `artifact_contents`)

`artifact_contents` có `ON DELETE CASCADE` theo `artifacts.id`, nên xóa metadata sẽ xóa luôn bytes.

```sql
BEGIN;
SELECT id, kind, created_at FROM artifacts WHERE workspace_id = $1 AND owner_run_id = $2;
DELETE FROM artifacts WHERE workspace_id = $1 AND owner_run_id = $2;
COMMIT;
```

Evidence và terminal receipt đang tham chiếu artifact đã xóa sẽ đọc thành `unavailable`, không phải
success rỗng (M11.2); đây là hành vi mong đợi.

## Kiểm tra sau khi xóa

- `SELECT count(*)` về 0 cho đúng scope; scope khác không đổi.
- Alert `artifact_mismatch` có thể báo cho run liên quan; ghi chú ticket rồi resolve.
- Backup cũ vẫn chứa dữ liệu. Áp retention của backup theo chính sách, không restore backup đó vào
  môi trường dùng chung.

## Giới hạn

Chưa có endpoint hay CLI purge tự động; runbook này là thao tác SQL thủ công có kiểm soát.
