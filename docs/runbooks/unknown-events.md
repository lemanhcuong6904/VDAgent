# Runbook: unknown event types (`unknown_events`)

**Alert**: "Runs emitted event types this deployment does not know"
**Severity**: warning

## What it means

A row in `platform_run_events` (last hour) has an `event_type` this build does not emit — a
newer producer is running against the same database, most often during a rolling deploy or a
canary. Consumers that fail on unknown types will break the run; the contract is to ignore
unknown fields and unknown event types.

## Diagnose

```sql
SELECT event_type, COUNT(*), MIN(created_at), MAX(created_at)
FROM platform_run_events
WHERE created_at > now() - interval '1 hour' AND NOT (event_type = ANY(ARRAY[
  'run.queued','run.leased','run.status','run.cancel_requested',
  'step.queued','step.started','step.completed','step.failed','agent.message',
  'approval.requested','approval.resolved','artifact.published','evidence.recorded','receipt.sealed']))
GROUP BY event_type ORDER BY COUNT(*) DESC;
```

Then check which versions are running (`GET /health` per replica) and whether the type is in
the newer release notes or is a typo in a producer.

## Act

1. **Expected new type**: add it to `KNOWN_EVENT_TYPES` in `src/alerts.ts` and to the event
   contract docs, then roll forward.
2. **Typo in a producer**: fix the emitter and, if the rows matter to a consumer, replay them
   after deletion with a corrective event rather than rewriting history.
3. **Rolling deploy in progress**: no action; the alert resolves once the old build is gone.

## Verify

The alert resolves when no unknown type appears in the last hour.

## Do not

- Do not make consumers strict about unknown event types — forward compatibility is the
  contract, and strictness turns a deploy into an outage.
- Do not edit `platform_run_events` rows; the journal is append-only.
