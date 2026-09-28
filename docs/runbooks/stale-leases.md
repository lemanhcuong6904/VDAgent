# Runbook: stale leases (`stale_leases`)

**Alert**: "Runner leases are past their lease time" / "Runner leases are long overdue"
**Severity**: warning at 60s overdue, critical at 300s (or any run still `leased` after the deadline)

## What it means

A worker claimed a run and then stopped heartbeating. `platform_runs.lease_until` has passed
while the status is still `leased` or `running`. Because the claim holds a `fencing_token`,
no other worker can take the run until the lease is reclaimed, so the run is stalled rather
than lost: its journal and checkpoint are intact.

## Diagnose

```sql
SELECT id, status, worker_id, attempt, lease_until, now() - lease_until AS overdue
FROM platform_runs
WHERE lease_until IS NOT NULL AND lease_until < now() AND status IN ('leased', 'running')
ORDER BY lease_until;
```

```bash
docker compose ps                     # is the worker container up?
docker compose logs --tail=200 worker # crash loop, OOM, blocked on a dependency?
```

Check whether the worker is alive but slow (a long tool call, a hung sandbox) versus gone.

## Act

1. **Worker down**: restart it. `docker compose up -d worker`. It reclaims expired leases
   on the next poll, and `attempt` increments.
2. **Worker alive but stuck**: let the lease expire and reclaim, or cancel the run if it is
   not making progress (`RunLedger.cancel`), which sets `cancel_requested` and the worker
   stops at the next checkpoint.
3. **Repeated for the same run**: check `platform_runs.attempt` against `max_attempts`. At
   the limit the run goes `failed` with an error rather than looping.
4. **Many runs at once**: treat it as a worker-capacity incident, not a run incident — the
   queue is deeper than the pool can drain.

## Verify

```sql
SELECT COUNT(*) FROM platform_runs
WHERE lease_until < now() AND status IN ('leased', 'running');  -- expect 0
```

The alert auto-resolves on the next evaluation once no run is overdue.

## Do not

- Do not update `lease_until` by hand to "unstick" a run: the fencing token is what keeps
  two workers from writing the same run, and a manual lease hides the real fault.
- Do not delete the run row. Reclaim and let it retry, or cancel it.
