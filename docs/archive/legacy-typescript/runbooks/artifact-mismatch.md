# Runbook: artifact mismatch (`artifact_mismatch`)

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Alert**: "Published artifact content does not match its hash" / "Artifact publication failed"
**Severity**: warning for failed publications, critical for a hash or length failure

## What it means

Either an artifact is `ready` without a valid SHA-256/length readback, or publication failed
and left an artifact in `status = 'failed'`. A ready artifact whose metadata does not match its
content is untrusted: a reader may consume different bytes than the receipt attests.

## Diagnose

```sql
SELECT id, workspace_id, owner_run_id, kind, version, status, sha256, bytes, created_at
FROM artifacts
WHERE status = 'failed' OR (status = 'ready' AND (sha256 IS NULL OR bytes IS NULL OR length(sha256) <> 64))
ORDER BY created_at DESC LIMIT 50;
```

```sql
-- Recheck one artifact against its stored content
SELECT a.id, a.sha256 AS recorded, a.bytes AS recorded_bytes,
       encode(digest(c.content, 'sha256'), 'hex') AS actual, length(c.content) AS actual_bytes
FROM artifacts a JOIN artifact_contents c ON c.artifact_id = a.id
WHERE a.id = $1;
```

## Act

1. **Publication failed**: re-run the producing step. `seal` is metadata-first, so a retry
   reuses the metadata and completes the missing content write.
2. **Hash or length mismatch**: treat the artifact as corrupt. Quarantine it (mark `failed`),
   republish from the source, and re-seal the affected terminal receipt.
3. **Metadata missing but content present**: recompute the hash from
   `artifact_contents` and record the readback before marking ready.
4. **Callers already read the artifact**: list them from evidence refs and tell them the
   revision is invalid — do not silently swap content under the same id.

## Verify

```sql
SELECT COUNT(*) FROM artifacts
WHERE status = 'ready' AND (sha256 IS NULL OR bytes IS NULL OR length(sha256) <> 64);  -- 0
```

## Do not

- Do not edit `sha256` to match the content: the hash is what evidence and receipts bind to.
- Do not mark a failed artifact ready without a readback; the alert would simply return.
