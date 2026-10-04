# Merging `origin/main` into `staging-agent`: audit and backend-v2 migration

**CURRENT BACKEND = the new `main` architecture (backend v2). The backend-v1 modules have been removed.**
Live code paths:
- `runtime/` (engine)
- `http/` (REST + SSE)
- `persistence/` (SQLAlchemy Core + Alembic)
- `mcp/catalog.py` + `mcp/handlers.py`
- `artifacts/`, `conversations/`, `scopes/`, `warehouse/`

Status as of 2026-09-30:
- Branch `integrate/main-into-staging` holds the merge, **uncommitted** (`MERGE_HEAD` set, no merge commit).
- `staging-agent` is unchanged at `f0aa36d`.
- Backups: `backup/staging-agent-f0aa36d`, `backup/origin-main-5dad7ac`.
- Nothing is committed or pushed.

## 1. Audit (before the migration)

**The rebase was aborted.**
- `git pull origin main` rebased because `pull.rebase=true` is set.
- The rebase replayed 8 old commits, including "sync" commits that re-added the whole project. That produced 42 conflicts in the third commit alone, with more expected in later commits.
- Nothing had been resolved, so the abort lost nothing.

**Merge instead of rebase.**
- A merge has 13 content conflicts, resolved once.
- The real risk was a silent break, not the conflicts themselves: `main`'s CORE restructure (PR #7) moved the live backend to new packages.
- Every staging integration feature, however, still lived in the old modules. After a textual merge those modules would be dead code:
  - `engine/`, `api/`
  - `db/artifact_store.py`, `db/repo.py`, `db/scopes.py`
  - `mcp/tools.py`
- `main`'s live MCP catalog had only 8 retail tools. There were no artifact tools, no `get_user_context` and no `re_*` tools.

**`main` itself had pre-existing debt:**
- `main`'s own suite gave 261 passed, 4 `test_architecture` failures, and 4 collection errors.
- The cause: the commit "chore: sync vde-agent-demo project" had re-added the old modules and old root tests next to the new packages.

## 2. Conflicts resolved (13, semantically; no global ours/theirs)

| File | Resolution |
|---|---|
| `backend/vdagent_backend/config.py` | Takes `main`'s version, where overrides come from `Config` fields. The field `re_warehouse_db` is kept, so `VDAGENT_RE_WAREHOUSE_DB` works automatically. |
| `backend/vdagent_backend/mcp/server.py` | Takes `main`. The staging `create_mcp` is dropped; `app.py` wires `McpTools` instead. |
| `backend/config.yaml`, `config.compose.yaml` | `main`'s per-plugin `mcp_tools` grants, filled with the WS1–WS7 permission matrix. `vdagent_chart` is kept, and `re_warehouse_db` is kept. |
| `data/seed_users.py` | `main`'s Alembic `migrate` and `Users.ensure`, followed by the staging B-10 `seed_missing_demo_scopes` (now `vdagent_backend.scopes`). |
| `agents/compare/…/settings.py`, `agents/insight/…/settings.py` | Docstrings combined: `main`'s wording plus the staging paragraphs. |
| `agents/insight/…/bridge.py` | Staging's version. Staging had rewritten the whole module; `main` had only edited the old docstring. |
| `Makefile` | Union: `main`'s `sdk-docs` / `sdk-docs-serve` plus staging's docker / offline / live targets. |
| `README.md` | Staging's Vietnamese onboarding, with `main`'s developer facts added: sdk-docs, adding a plugin with `mcp_tools`, the turn contract, memory. |
| `agents/{compare,insight,orchestrator}/README.md` | Staging's content. The "MCP tools granted" sentence now describes `mcp_tools` in `backend/config.yaml`. |

## 3. Features ported to backend v2 (TDD: each subsystem RED first, then GREEN)

| Feature | Old path (staging) | New path (backend v2) | Tests |
|---|---|---|---|
| Artifact envelopes (put / get / list, versioning, SUPERSEDED, hash, snapshot / semantic / lineage checks, F-02 verify) | `db/artifact_store.py` | `artifacts/envelopes.py` `EnvelopeStore`, `verify_envelope`, through `ArtifactService.put/get/list_envelopes` | `tests/artifacts/test_envelopes.py` (20) |
| Schema: `artifacts` + immutability triggers, `user_scopes`, `tasks.outcome`, `tasks.idempotency_key` + unique index | `db/schema.sql` + `database._migrate` | `persistence/tables.py` + Alembic `0003_artifacts_scopes_outcome.py`. Adopts staging databases in place; downgrade keeps the status CHECK. | `tests/persistence/test_migrate_ws.py` (3); `main`'s metadata test |
| User scopes, `get_user_context`, B-10 seeding | `db/scopes.py` | new unit `scopes/` (`UserScopes`, `seed_missing_demo_scopes`), added to the dependency rule | `tests/scopes/test_scopes.py` (8) |
| `re_*` tools (scoped SQL, F-08: no hidden-row count) | `mcp/re_sql.py` + `mcp/tools.py` | `warehouse/re_sql.py` + `warehouse/realestate.py` `RealEstateWarehouse` | `tests/mcp/test_mcp_ws.py` |
| `artifact_put/get/list`, `get_user_context`, `re_list_tables/re_describe_table/re_run_query`, `WRITABLE_TYPES` | `mcp/tools.py` | `mcp/catalog.py` (tools + `RESULT_FIELDS`) + `mcp/handlers.py` | `tests/mcp/test_mcp_ws.py` (18), `main`'s `test_mcp_server.py` extended to every tool |
| Permission matrix | `PERMISSIONS` dict | `mcp_tools` grants in `backend/config.yaml`; a test compares them to the matrix | `test_configured_grants_are_the_permission_matrix` |
| `McpIdentity.task_id` (artifacts are filed under the run) | `tokens.py` | `core/tokens.py` (default `""`); `runtime` issues tokens with `run.task_id` | `test_mcp_identity_carries_the_task…` |
| `save_report` `{{chart_spec:id@v}}` embeds | `mcp/tools.py` | `ArtifactService.save_report` | `test_save_report_embeds_only_this_users_chart_specs` |
| `/api/chart-specs/{id}/{version}` | `api/rest.py` | `http/artifacts.py` + `ArtifactService.get_chart_spec` | `tests/http/test_ws7_api.py` |
| F-03 run outcome | `engine/context.py` / `engine.py` | `runtime/context.py` `TurnContext.report_outcome`, `Run.outcome`, `Tasks.finish_task(outcome)`, `task_dto.outcome` | `tests/runtime/test_ws7_runtime.py`, `tests/http/test_ws7_api.py` |
| F-04 startup recovery (task `failed/interrupted`, run_state → `interrupted`, no resume) | `engine.recover` | `Tasks.fail_running_tasks` sets `interrupted`; `Engine(on_interrupted=…)`, wired in `app.py` to `ArtifactService.interrupt_run` (runtime may not import artifacts) | runtime tests + acceptance kill -9 |
| F-11 `Idempotency-Key` | `engine.post_message`, `api/rest.py` | `runtime/engine.py` `post_message(idempotency_key)` + `IdempotencyConflictError`; `Tasks.find_keyed_task`; `http/agents.py` header → 200 / 409 | runtime + http tests |
| F-09 Vega-Lite v6 for `create_chart` | `mcp/charts.py` | `artifacts/charts.py` | `test_create_chart_emits_renderable_vega_lite_v6` |
| Six-agent DAG (Orchestrator LLM planner, StepSpec paths of the 5 workers) | unchanged agent code | unchanged: now runs on `runtime.Engine` + new `McpTools` | agent suites moved to backend v2 (below) |

## 4. Compatibility adapters

| Adapter | Where | Why | Removal criterion |
|---|---|---|---|
| `GrantedTools` (**test only**) | `agents/data/vdagent_data/tests/conftest.py` | Keeps the agent tests' old `call(identity, name, args)` signature. It applies the real `backend/config.yaml` grants per caller agent on top of backend-v2 `McpTools`. | Remove when every agent test calls `McpTools.call(identity, granted, name, args)` directly. |
| `McpIdentity.task_id` default `""` | `core/tokens.py` | Existing callers of `TokenRegistry.issue(user, agent, inv)` stay valid; the runtime always passes the task. | Make it required once no caller omits it. |

There are no production adapters. The live app uses only backend-v2 modules.

## 5. Old modules — REMOVED in the cleanup step (2026-09-30)

- **Where:** `backend/vdagent_backend/` holds `api/`, `db/` (including `schema.sql`), `engine/`, `events.py`, `ids.py`, `tokens.py`, `plugins.py` (shadowed by the `plugins/` package), `mcp/tools.py`, `mcp/re_sql.py`, `mcp/sql.py`, `mcp/charts.py`.
- **Evidence that they are dead:**
  - Booting the real app loaded all 6 agents, and **no** old module was imported at runtime.
  - A repository scan finds references to them only from each other, plus the archived evidence script `docs/integration/ws7_audit_evidence/lineage_audit.py`.
- **Tests removed:** the 10 root tests that exercised only these modules. Their staging-specific cases were ported first (§3):
  - `test_api`, `test_engine`, `test_mcp_server`, `test_memory` (stale duplicates of `main`'s sub-folder tests)
  - `test_artifact_store`, `test_mcp_artifacts`, `test_mcp_re_tools`, `test_user_context`, `test_seed_scopes`, `test_ws7_remediation`
- **Removed (cleanup).** The 25 files above are gone (`git rm`, uncommitted). Before deleting them, the checks were
  repeated: no reference from outside the set, and no packaging or Docker reference.
- The package `re_warehouse` now documents "May import:" and declares `__all__`. That missing docstring had been
  hidden behind the `api` failure.
- The archived script `docs/integration/ws7_audit_evidence/lineage_audit.py` is kept as the historical v1 audit record
  and no longer runs. Its maintained successor is `acceptance/ws7/test_lineage.py`.
  - Removing them turns the 4 `test_architecture` failures green; those failures are caused only by these modules (verified by re-running the rule on every import).
  - `tests/fixtures/staging_schema.sql` keeps the old schema for the adoption test.

## 6. Verification

| Check | Result |
|---|---|
| `main`'s own suite (baseline, scratch worktree) | 261 passed, 4 architecture failures, 4 collection errors (stale tests) |
| Backend suite (merged) | 263 passed, 4 failed: the same `test_architecture` failures, caused only by the old modules |
| Host full suite | **1314 passed, 29 skipped**, same 4 architecture failures |
| Docker `tests` image | **1314 passed, 29 skipped**, same 4 |
| Agent suites on backend v2 (Data, Insight, Compare, Chart, Report, Orchestrator) | all green. This includes the real-engine six-plugin golden with B2 ∥ B3 on `runtime.Engine`. |
| Frontend build + Vitest | PASS, 10/10 |
| `acceptance/ws7/run.sh` (fresh offline stack on the merged image) | **PASS 14/14**: REST golden, real browser 5/5 charts with a clean console, store audit 7/7, kill -9 giving `failed/interrupted` with run_state `running → interrupted` |
| Copy of the user's running live DB (staging schema) migrated with the new image | adopted to `0003`: 4 tasks (outcomes kept), 51 artifacts, 43 datasets (moved into 915 `dataset_rows`), 1 report, 2 scopes; nothing lost |
| Live stack via `make docker-live-up` / `docker-live-check` (isolated project on :8023) | `ORCH_LLM on`, `SNAP-2026-09-28`, `sc-1`, `healthy`, 6 agents, "LLM planner on (model gpt-4o-mini)" |
| `git diff --check` | clean |

## 7. Live happy cases on backend v2 (OpenAI `gpt-4o-mini` planner; Insight `gpt-6-luna`)

| HC | Plan produced by the LLM (waves) | Task | Result |
|---|---|---|---|
| HC1 | data → insight `[[B1],[B2]]` | `t_03ae934efcef` | completed / partial |
| HC2 | data → compare `[[B1],[B2]]` | `t_6abdaca3e649` | 5 peers, B-11 visible |
| HC3 | data → [insight ∥ compare] → chart `[[B1],[B2,B3],[B4]]` | `t_324d918b704f` | 5 charts; B2 and B3 started in the same ms |
| HC4 | data → [insight ∥ compare] → chart → report `[[B1],[B2,B3],[B4],[B5]]` | `t_83903208ef05` | 6 agents; browser 5/5 SVG, 0 console messages; lineage 7/7; no PRJ-Y / D12-09 |

- Canonical facts are unchanged: DOM 138 vs 61; 72,500,000 vs 64,500,000 VND/m²; gap 12.40%; 5 peers; B-11 shown.
- Idempotency: retrying HC4 with one `Idempotency-Key` gave 202, then 200 with `deduplicated: true` and the same task.

## 7b. After the cleanup: zero-fail regression (2026-09-30)

| Check | Result |
|---|---|
| `test_architecture` | **4/4 passed** |
| Host full suite | **1318 passed, 29 skipped, 0 failed** (the 1 warning is the known `ux_user_scopes` reflection `SAWarning`) |
| Docker `tests` image | **1318 passed, 29 skipped, 0 failed** |
| Real app boot | 6 agents loaded |
| Frontend | build PASS, Vitest 10/10 |
| `acceptance/ws7/run.sh` | **PASS 14/14**; kill -9 gives task `failed/interrupted`, run_state `running → interrupted`; browser 5/5 |
| Live `make docker-live-up/check` (isolated project, :8023) | `ORCH_LLM on`, pins OK, `healthy`, 6 agents, LLM planner on |
| Live HC1–HC4 | waves `[[B1],[B2]]`, `[[B1],[B2]]`, `[[B1],[B2,B3],[B4]]`, `[[B1],[B2,B3],[B4],[B5]]`; all completed / partial; HC4 browser 5/5, lineage 7/7 |
| `git diff --check` | clean |

Evidence: [backend_v2_migration_evidence/after_cleanup/](backend_v2_migration_evidence/after_cleanup/).

## 8. Remaining risks

1. ~~Four `test_architecture` failures~~: **resolved** by the cleanup (§5, §7b).
2. **HC1 wording (observed live).** Insight's LLM wrote "+12,4% so với 7 căn".
   - The 7 is a bound value (`dm_unit_friction_diagnostics.peer_count`, the DW's own peer count behind the 12.40% spread), not a hallucination.
   - It sits next to Compare's 5 peers, so it can confuse a demo.
   - This is pre-existing Insight behaviour tied to **B-11**; it was not changed here.
3. **Your running containers use the pre-merge image.** `team_6_cai-backend-live-1` and `team_6_cai-backend-1` were left untouched.
   - After approval, `make docker-live-up` recreates the live stack.
   - Its database is migrated in place (verified on a copy).
4. `ux_user_scopes` is an expression index that Alembic cannot reflect. It produces a harmless `SAWarning` in `main`'s metadata-comparison test.
5. Business blockers are unchanged: B-11, B-2, D2b, B-3, B-12, F-05.

## 9. Ready to merge into `staging-agent`?

**YES.** The cleanup is done and the regression has zero failures (§7b). Only your approval is pending.

Everything else passed, and no functionality from either side was lost. Nothing has been committed. Next steps, on approval:
1. Commit the merge on `integrate/main-into-staging`.
2. Optionally commit the cleanup.
3. Merge into `staging-agent`.
