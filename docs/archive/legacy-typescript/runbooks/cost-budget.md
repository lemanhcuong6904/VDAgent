# Runbook: cost budget (`cost_budget`)

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Alert**: "Spend is close to its budget" / "Spend passed its budget"
**Severity**: warning at 80% of budget, critical at 100%

## What it means

`platform_usage_records.estimated_cost` summed over the window (default 24h) has reached the
configured budget for a space. Budgets come from `RUN_COST_BUDGET_<space_id>` or the shared
`RUN_COST_BUDGET`; with neither set the signal stays silent.

## Diagnose

```sql
SELECT kind, model, agent_id, COUNT(*), SUM(input_tokens) AS in_tok,
       SUM(output_tokens) AS out_tok, SUM(estimated_cost) AS cost
FROM platform_usage_records
WHERE space_id = $1 AND created_at > now() - interval '24 hours'
GROUP BY kind, model, agent_id
ORDER BY cost DESC;
```

```sql
SELECT run_id, SUM(estimated_cost) AS cost, COUNT(*) AS calls
FROM platform_usage_records
WHERE space_id = $1 AND created_at > now() - interval '24 hours'
GROUP BY run_id ORDER BY cost DESC LIMIT 10;
```

Look for a retry loop, a runaway child fan-out, or a larger model than the task needs.

## Act

1. **Single runaway run**: cancel it. It stops at the next checkpoint and its spend stops.
2. **Systemic**: lower `max_attempts`, cap child fan-out, or route the affected capability to
   a smaller model in the model registry.
3. **Budget is simply too low**: raise `RUN_COST_BUDGET_<space_id>` with an owner's approval —
   do not silence the alert by deleting it.
4. **Cheap-model regression**: if `estimatedCost` looks wrong for the token counts, check the
   model registry pricing before assuming real overspend.

## Verify

Re-run the sum after the change; it should fall under the budget within the window.

## Do not

- Do not delete usage records to bring the sum down — they are the billing evidence.
- Do not disable the alert for a space without a replacement budget.
