# Runbook: PII leak (`pii_leak`)

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Alert**: "Personal data reached telemetry or the audit journal"
**Severity**: critical, no warning tier

## What it means

Scanning recent `observability_logs` and `platform_audit_events` found a value shaped like an
email address, payment card, US SSN, bearer token, private key or inline secret. Redaction in
`Observability` and `recordAudit` is expected to prevent this, so a finding means either a new
field bypassed it or something wrote to the table directly. The alert lists finding types and
row references only — never the matched value.

## Diagnose

```sql
SELECT id, timestamp, level, message, data, trace_id
FROM observability_logs
WHERE id = $1;   -- reference from the alert

SELECT id, created_at, actor, action, resource_type, metadata
FROM platform_audit_events WHERE id = $1;
```

Identify which key or message carried the value, then find the writer:

```bash
grep -rn "the-field-name" src/
```

Likely causes: a key outside the `SENSITIVE_KEY` list, a value interpolated into the message
instead of passing through `data`, or a direct `INSERT` that skipped `recordAudit`.

## Act

1. **Contain**: remove the rows containing the value.
   ```sql
   DELETE FROM observability_logs WHERE id = ANY($1);
   ```
   If the value reached an external exporter, treat it as disclosed and follow your incident
   process (rotation, notification) — deletion here does not recall it.
2. **Fix upstream**: add the key to `SENSITIVE_KEY` in `src/otel-observability.ts` or to the
   audit redaction list, and add a regression test with a realistic sample.
3. **Rotate** anything the value could authenticate: tokens, keys, session material.
4. **Widen detection** if the shape was not caught: add a pattern to `PII_PATTERNS` in
   `src/alerts.ts` with a test.

## Verify

```sql
SELECT COUNT(*) FROM observability_logs
WHERE message ~* '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}';  -- 0
```

Then run the alert evaluation again; it resolves only when no finding remains.

## Do not

- Do not paste the matched value into an incident channel or a ticket.
- Do not silence the signal by shortening the scan window; the next evaluation must still find it.
