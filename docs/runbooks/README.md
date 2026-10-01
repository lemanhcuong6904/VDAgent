# Runbooks

Mỗi runbook gắn với alert hoặc thao tác vận hành trong PLAN §10. Tổng quan vận hành:
[operations](../operations.md).

| Tình huống | Runbook |
| --- | --- |
| Khởi động, shutdown, worker drain, readiness | [graceful-shutdown](graceful-shutdown.md) |
| Migration, canary deploy, rollback, kill-switch agent/version | [canary-rollback](canary-rollback.md) |
| Backup, restore DB, artifact hash restore, reconcile sau restore | [backup-restore](backup-restore.md) |
| Outbox lag, dead-letter, replay outbox | [outbox-lag](outbox-lag.md) |
| Lease quá hạn, worker chết | [stale-leases](stale-leases.md) |
| Event/effect `unknown`, reconcile thay vì retry mù | [unknown-events](unknown-events.md) |
| Artifact hash/length mismatch | [artifact-mismatch](artifact-mismatch.md) |
| Vượt ngân sách cost, disable provider/agent | [cost-budget](cost-budget.md) |
| Rò rỉ PII/secret trong log hoặc memory | [pii-leak](pii-leak.md) |
| Purge memory hoặc artifact theo yêu cầu xóa | [purge-memory-artifact](purge-memory-artifact.md) |
| Dependency scan, SBOM, image pin, rotate secret | [security-scan](security-scan.md) |

Alert evaluation chạy tự động bằng `AlertScheduler` trong worker, mặc định mỗi 60 giây
(`ALERT_EVAL_INTERVAL_MS`; đặt `0` để tắt nếu dùng cron ngoài).
