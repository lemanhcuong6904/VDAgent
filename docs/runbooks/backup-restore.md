# Runbook: PostgreSQL backup, restore and recovery (M13.2)

PostgreSQL is the only source of truth: runs, events, outbox, sessions, memory, artifacts
(`artifact_contents` holds the bytes), evidence and receipts. A logical dump of the database is a
complete backup. There is no object store to back up separately.

## Backup

```bash
pg_dump --format=custom --no-owner --file=team6-$(date -u +%Y%m%dT%H%M%SZ).dump "$DATABASE_URL"
sha256sum team6-*.dump > team6.dump.sha256
```

Store the dump and its checksum together, off the database host. Custom format is required for
selective or parallel restore (`pg_restore -j`).

## Restore

1. **Stop writers first.** Scale the API and workers to zero, or set `PLATFORM_RUNNER_MODE` so no
   worker claims. A worker running against a half-restored database can lease runs twice.
2. Verify the dump: `sha256sum -c team6.dump.sha256`.
3. Restore into an **empty** database:
   `createdb team6_restored && pg_restore --no-owner --exit-on-error -d team6_restored team6-*.dump`
4. Point `DATABASE_URL` at it and start **one** API replica. Check `GET /ready`:
   - `schema: ok` — proceed.
   - `schema: pending` — the image is newer than the dump; startup ran the pending migrations.
   - `schema: ahead` — the image is **older** than the dump. Deploy the image that wrote it.
5. Start workers. Then check:
   - Runs leased at backup time are re-claimed once their `lease_until` passes, with a new fencing
     token. The old holder's writes are rejected by the token. See `stale-leases.md`.
   - Outbox rows unpublished at backup time are delivered. The outbox is at-least-once across a
     restore: an event published after the dump but before the failure is delivered again, so
     consumers must dedupe on `outbox_id`.
   - A client retrying a request with its idempotency key gets the restored run, not a new one.

## What a restore can lose

Everything committed after the dump. A run created after the dump is gone. Its client retries
with the same idempotency key and creates it again, which is correct. An external effect a tool
performed after the dump is **not** visible in the restored ledger. If the tool had sealed a
terminal receipt, the receipt is lost too. Treat those runs as `unknown` and reconcile against
the external system before re-running (PLAN §15.5). Do not assume "no receipt" means "not done".

## Rehearsal

```bash
bash scripts/rehearse-backup-restore.sh                           # must pass
REHEARSAL_CORRUPT=artifact bash scripts/rehearse-backup-restore.sh  # must FAIL
```

The rehearsal creates two throwaway databases (names contain `rehearsal`; it refuses any other),
seeds a known state, dumps, restores into the second database and checks 10 properties: row counts,
schema status, artifact bytes re-hashed from the restored content, session rows byte-identical,
sequences continuing past restored ids, stale-lease re-claim with a higher fencing token,
rejection of the dead worker's old token, outbox delivery exactly once after restore, idempotent
replay onto the restored run, and receipt lookup preventing a re-run. The negative control flips
one byte in a restored artifact and must fail only the hash check.

Receipts: `docs/execution/receipts/M13.2-backup-restore.json` and
`M13.2-backup-restore-negative-control.json`.

## Not rehearsed

Point-in-time recovery (WAL archiving / `pg_basebackup`), cross-region copy and restore at
production size. The rehearsal dump is ~73 KB. Restore time at real volume must be measured
on the production host (M13.6, owner approval).
