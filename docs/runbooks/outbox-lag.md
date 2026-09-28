# Runbook: outbox lag (`outbox_lag`)

**Alert**: "Outbox delivery is lagging" / "Outbox delivery is stalled"
**Severity**: warning at 60s lag or 1000 pending, critical at 300s or any event that has
exhausted its publish attempts

## What it means

`platform_outbox_events` holds committed events that downstream consumers have not received
yet (`published_at IS NULL`). The run journal is already committed, so this is a delivery
delay, not data loss — consumers will catch up once publishing resumes.

## Diagnose

```sql
SELECT COUNT(*), MIN(created_at), now() - MIN(created_at) AS lag
FROM platform_outbox_events WHERE published_at IS NULL;

SELECT id, run_id, event_type, attempts, claimed_by, claimed_until, last_error
FROM platform_outbox_events
WHERE published_at IS NULL
ORDER BY id
LIMIT 20;
```

- `claimed_by` set with a future `claimed_until`: a publisher holds the batch — check that
  process is alive.
- `attempts` climbing with `last_error`: the consumer is rejecting the event.
- Nothing claimed: no publisher is running, or it is stopping between polls.

## Act

1. **Publisher down**: restart it. `OutboxPublisher.start()` reclaims expired claims and
   resumes from the oldest unpublished row.
2. **Consumer rejecting** (`last_error`): fix the consumer, then confirm the events publish.
   Events are not dropped at the attempt limit — `attempts >= 5` only raises the alert.
3. **Slow consumer**: increase `batchSize`/reduce `pollMs`, or scale consumer replicas.
4. **Poison event**: if one event blocks the head of the queue, record the reason in the
   incident, then mark it published out of band so the rest can drain.

## Verify

```sql
SELECT COUNT(*) FROM platform_outbox_events WHERE published_at IS NULL;  -- trending to 0
```

The alert resolves when lag falls below the warning threshold and no event is exhausted.

## Do not

- Do not delete unpublished events: consumers would never see the transition and would
  diverge from the ledger.
- Do not mark events published without delivering them; the outbox is the delivery record.
