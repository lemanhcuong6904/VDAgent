# AGENTS.md — VDaAgent repository guide

## Guideline

- Don't use sub agent
- Use TTD for development
- Do not commit secrets. Every `agents/<name>/.env` is gitignored; change the `.env.example` next to it.

This file holds the **binding engineering rules and the current verified state** of the repository, for people and
coding agents that change it. It is not a tutorial (see [README.md](README.md)) and not the architecture reference
(see [docs/architecture/system.md](docs/architecture/system.md)). Documentation index: [docs/README.md](docs/README.md).

State as of **2026-10-04**: branch `main`, base `aed2917` plus the staged Phase 1–6A change set (not committed).
The status log that this file carried until Phase 6A (baseline audit, workstreams WS1–WS7, live validations,
backend-v2 migration, Phases 2–5) is archived verbatim in
[docs/archive/agents-history-2026-09.md](docs/archive/agents-history-2026-09.md).

---

## 1. Engineering rules and invariants

**Working rules**

- TDD: write the failing test first; never skip, xfail or weaken a test, and never change an expected value without
  evidence (reproduce, find the commit that changed the behaviour, then update).
- Code and tests win over documents. A change of behaviour updates its canonical document in the same change.
- Never commit or push without an explicit request. Never reset, revert, force-push or rewrite history of shared
  branches.
- Never write to the AWS warehouse. The application and the agents are read-only clients.
- Never edit a user's `.env`; never print secret values (names only).

**Plugin rules** (contract: the `sdk/vdagent_sdk` module docstring, `make sdk-docs`)

- Each plugin exports `setup(api, opts)` and depends only on `vdagent_sdk` (plus `vdagent_contracts` /
  `vdagent_agentkit`). Plugins share one process and one event loop: never block the loop, never write `os.environ`,
  keep per-user state in `ctx.memory`, not on the agent object.
- A turn reports through `ctx`: `emit_assistant`, then exactly one result per tool call (`emit_tool_result`; for
  `send_to_agent`, `call_agent` first), and ends with a step without tool calls. Wrong order →
  `contract violation: …`.
- Agents talk to each other only through `send_to_agent` (`ctx.call_agent`) and share data only through MCP artifacts
  (`artifact_put` / `artifact_get`), never through local files.
- MCP tool grants are per plugin: `mcp_tools: [...]` in `backend/config.yaml` and `backend/config.compose.yaml`. Each
  agent may write only its own artifact types (`WRITABLE_TYPES`, enforced by the Backend).
- A plugin's own `.env` (`agents/<name>/.env`) wins over the process environment; it is read with `dotenv_values`,
  never exported.

**Product invariants**

- The Orchestrator executes a code-validated DAG. The LLM may propose only intent and plan structure; specs, pins,
  ids, bindings and dependency modes are written by code. A rejected plan fails safely and calls no agent; there is
  **no silent fallback** to the deterministic planner.
- Missing values stay `null` with a limitation code (`METRIC_UNAVAILABLE`, `WINDOW_INCOMPLETE`); never 0, never invented.
- Findings are associations, not causes. Insight wording stays associative.
- Peer area is `net_area_m2` only (D9, `contracts/vdagent_contracts/peer_rules.py`); no `area_m2` fallback.
- Chart never recomputes values; Report never runs new analysis. Every number in a chart or report carries a
  `source_ref` that resolves exactly.
- Scope always comes from the Backend (`get_user_context`, scoped `re_run_query`), never from a message.

## 2. Architecture summary

```text
Web UI (frontend/, React + Vite)  ·  REST POST /api/agents/{agent}/messages  (+ SSE)
        ↓
Backend FastAPI (backend/vdagent_backend): runtime engine, http, MCP server, artifact store, persistence
        ↓   six plugins in one process
Orchestrator ── B1 ──> Data ── B2 ──> Insight ─┐
                          └── B3 ──> Compare ──┴─ B4 ──> Chart ── B5 ──> Report ──> answer + rp_… (6 sections)
        ↓ read-only, scoped
Warehouse: AWS RDS cdw, view layer re over schema gold   (test/offline: explicit SQLite mock)
```

- Waves are `[[B1], [B2, B3], [B4], [B5]]`; B2 and B3 run concurrently on identical B1 refs. Chat mode stops at B4;
  a report request adds B5.
- Only the Orchestrator planner and Insight narration use an LLM on the main path. Data, Compare, Chart and Report
  `StepSpec@1` operations are deterministic.
- Messages: `StepSpec@1` in, exactly one `AgentReport@1` out per step (`contracts/vdagent_contracts/messages.py`,
  `reports.py`). Operations are declared in the frozen catalogs `contracts/vdagent_contracts/catalogs/*.json`.

Full reference: [docs/architecture/system.md](docs/architecture/system.md); decisions D1–D10:
[docs/architecture/decisions.md](docs/architecture/decisions.md).

## 3. Repository layout

| Path | Contents |
|---|---|
| `backend/vdagent_backend/` | `app.py`, `config.py`; `runtime/` (engine, wait-for graph, context), `http/` (REST + SSE), `mcp/` (`catalog.py`, `handlers.py`, `server.py`), `artifacts/` (envelopes, charts, service), `persistence/` (SQLAlchemy Core + Alembic), `conversations/`, `memory/`, `scopes/`, `plugins/`, `core/`, `warehouse/` (`realestate.py`, `re_pg.py`, `re_sql.py`, `sql.py`), `re_warehouse/` (SQLite mock schema) |
| `backend/config.yaml`, `config.compose.yaml` | plugin list and per-plugin `mcp_tools` |
| `agents/{orchestrator,data,insight,compare,chart,report}/` | the six plugins (`vdagent_<name>/`, tests inside the package) |
| `agents/_shared/vdagent_agentkit/`, `agents/_template/` | shared LLM/MCP kit; plugin template |
| `contracts/vdagent_contracts/` | envelope, messages, reports, catalogs, step inputs resolver, peer rules, Vega-Lite validator |
| `sdk/vdagent_sdk/` | plugin interface (`Agent`, `InvocationContext`, `PluginAPI`) |
| `frontend/` | React + Vite UI (own `package.json`, Vitest) |
| `data/` | seeders only: `seed_warehouse.py`, `seed_re_warehouse.py`, `seed_users.py` |
| `warehouse/` | `backup/` (DR dump + README), `id_registry.json`, `schema_final_16_tables.sql`, `SNAPSHOT_RULES.md` |
| `docker/` | `check-env.sh`, `check_warehouse.py`, `seed-if-missing.sh`, `warehouse/{canonical_views.sql,apply-views.sh}` |
| `acceptance/ws7/` | offline acceptance (REST golden, lineage, restart, browser) and `run.sh` |
| `scripts/check_secrets.py` | secret scan (`make secret-check`) |
| `Dockerfile.python`, `docker-compose.yml`, `Makefile`, `dev.ps1` | build and run |
| `docs/` | documentation, index in [docs/README.md](docs/README.md) |

Retired and removed (recoverable from commit `aed2917`): the CSV warehouse pipeline and raw packs (Phases 2–3), the
TypeScript platform (`src/`, `test/`, `db/`, `schemas/`, `sdk/python/`, root `package.json`, Phase 4), backend v1
(`api/`, `db/`, `engine/`, `events.py`, `ids.py`, `tokens.py`, `plugins.py`, `mcp/{tools,charts,sql}.py`, Phase 5).
Do not reintroduce them.

## 4. Warehouse source of truth

```text
Production source of truth : AWS RDS PostgreSQL, database cdw
Runtime read layer         : schema re  (views from docker/warehouse/canonical_views.sql)
Canonical schema           : gold
Read role                  : vdagent_reader (read-only transactions, scoped TEMP views)
Units (re.dim_unit_master) : 47,713   (make warehouse-check, 2026-10-04)
```

- Path in code: root `.env` → `VDAGENT_RE_WAREHOUSE_DB` (→ `Config.re_warehouse_db`) → `RealEstateWarehouse`
  ([realestate.py](backend/vdagent_backend/warehouse/realestate.py)) → `re_pg` → AWS `cdw.re.*`.
- Every Data `dataset` records its source in `payload.snapshot.warehouse` (`backend: postgresql`, host, database).
- Warehouse data belongs to the DATA team in the canonical store; changes go there first, then the DR dump is refreshed.
  The application repo stores no canonical warehouse CSV datasets and no raw packs
  ([GIT_RULE.md §9.1](GIT_RULE.md)).
- Disaster recovery: `warehouse/backup/cdw_gold_snapshot_20260630.dump` (`pg_restore`, schema `gold`) with
  `schema_backup.sql`, `load_pg.sql` (reference only) and `docker/warehouse/{canonical_views.sql,apply-views.sh}`.
  Procedure: [warehouse/backup/README.md](warehouse/backup/README.md). A new dump comes from `gold`
  (`pg_dump -n gold -Fc`), never from CSV.
- Removed data is listed in [docs/data-archive/phase3-manifest.json](docs/data-archive/phase3-manifest.json) (path,
  size, sha256, git blob); restore with `git checkout aed2917 -- <path>` and check the sha256.

## 5. Snapshot and semantic pin

| Store | Snapshot | Semantic | Golden unit |
|---|---|---|---|
| Production (AWS `cdw`) | `SNAP-20260630-01` (APPROVED) | `3.1.0` | `MAS-U03832` |
| SQLite mock | `SNAP-2026-09-28` | `sc-1` | `A12-08` |

- A run pins exactly one snapshot and one semantic version. Free text gets them from `ORCH_SNAPSHOT_ID` /
  `ORCH_SEMANTIC_VERSION`; unset → `SNAPSHOT_REQUIRED` / `SEMANTIC_VERSION_REQUIRED`. Never "latest".
- Data accepts only an explicit APPROVED snapshot; DRAFT (`SNAP-2026-09-29` in the mock), unknown or `latest` are
  rejected (`steps._pin_snapshot`).
- The real warehouse has no snapshot-approval column: the `re` views write `APPROVED`, so results carry
  `SNAPSHOT_STATUS_ASSUMED` until the DATA team confirms.
- The artifact store rejects any artifact whose inputs disagree on snapshot or semantic version.

## 6. Production vs mock policy

- `VDAGENT_RE_WAREHOUSE_DB` has **no default**. Unset, empty, a PostgreSQL DSN without host or database, or any other
  `scheme://` → `ReWarehouseConfigError` at `create_app`; the Backend does not start. The message names the variable,
  never a credential.
- A `postgresql://` DSN → PostgreSQL. An unreachable warehouse fails the query (`warehouse unavailable: …`) and is
  **never** replaced by the mock; `make up` stops earlier in `docker/check-env.sh` / `warehouse-check`.
- A plain file path → the SQLite mock, **only when named explicitly**, logged at WARNING
  (`Warehouse backend: SQLite (synthetic mock)`). The offline compose services set
  `VDAGENT_RE_WAREHOUSE_DB: ./var/re_warehouse.db`; `backend/tests/conftest.py` names a per-test path.
- `data/seed_re_warehouse.py` refuses a DSN (exit 2) and only writes the mock.
- One selection path only: `RealEstateWarehouse` (+ `re_pg` / `re_sql`). `VDAGENT_WAREHOUSE_MODE` and the other
  `VDAGENT_RE_WAREHOUSE_*` variants are read by nothing.
- The mock (`SNAP-2026-09-28` / `sc-1`, synthetic `net_area_m2`) is for unit tests, golden cases and offline work
  (`make mock-up`, `acceptance/ws7/run.sh`). It is not a production source.
- Compare's legacy free-text path may read an externally supplied VHOP pack (`VDAGENT_VHOP_DATA_DIR`); none is
  shipped, and `compare_to_peers` reads only Data artifacts. Chart demo data needs `CHART_DEMO=on` and never runs in
  production (D6).

## 7. Docker and runtime rules

- One image, `Dockerfile.python`: stage 1 builds `frontend/` on **Node 22** (`node:22-slim`); the `runtime` stage
  serves UI, REST/SSE and MCP on one port with a healthcheck; the `test` stage runs the suite without network.
- The image copies only `data/seed_{warehouse,re_warehouse,users}.py` from `data/`; `.dockerignore` keeps `warehouse/`
  and raw data out of the build context. The test stage also carries `README.md`, `dev.ps1`, `Dockerfile.python`,
  `.dockerignore`, `scripts/` and installs `make` and `git` (read by Docker-setup and secret-scan tests).
- The only Node project is `frontend/`; there is no root `package.json`, no `pnpm`, no linter (static checks are
  `tsc --noEmit` inside `npm run build`).
- Python 3.12 via `uv`; `uv.lock` is current (`uv lock --check` passes with uv 0.11 and 0.12). Use `uv run --frozen`
  in scripts that must not touch the lock.
- Configuration: root `.env` (from `.env.example`: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`,
  `VDAGENT_RE_WAREHOUSE_DB`, `ORCH_SNAPSHOT_ID`, `ORCH_SEMANTIC_VERSION`); optional `agents/<name>/.env` and
  `backend/.env` (`VDAGENT_<KEY>` overrides).

| Switch | Effect |
|---|---|
| `ORCH_LLM=on` / `off` | LLM planner (production) / deterministic classifier (mock stack, no key) |
| `ORCH_LEGACY_LOOP=on` | old free-text tool loop, outside the DAG; debug only |
| `ORCH_DAG_TIMEOUT_S` | whole-run deadline (default 300 s) → `timed_out`, `DEADLINE_EXCEEDED` |
| `DATA_LLM=off` | Data serves `StepSpec@1` only (no chat; template narration) |
| `INSIGHT_LLM=off`, `COMPARE_LLM=off`, `REPORT_LLM=off` | template / rules mode; Report then serves `draft_report` only |
| `CHART_DEMO=on` | enables `chart demo` / `chart ask`; never in production |

- Runtime guarantees: `Idempotency-Key` on `POST /api/agents/{agent}/messages` deduplicates per (user, agent, key);
  the same key with different content → 409. Root runs report `tasks.outcome` (`completed | partial | failed |
  interrupted`) through `ctx.report_outcome`; a failed run gives `task.status = failed`. A Backend restart marks
  running tasks `failed / interrupted` and writes an `interrupted` run_state version; there is no automatic resume.

## 8. Artifact and lineage rules

- Every artifact is an `ArtifactEnvelope` with id, version, `content_hash`, producer, snapshot, semantic version and
  hash-pinned `input_artifact_refs` (`contracts/vdagent_contracts/envelope.py`). Stored hashes are never rewritten;
  verify a stored artifact with `verify_envelope` (`backend/vdagent_backend/artifacts/envelopes.py`), not by
  recomputing the hash; a SUPERSEDED version verifies against its status at write time.
- `source_ref` format: `<artifact_id>@<version>#<JSON pointer>`.
- Consumers read inputs only through the shared resolvers in `contracts/vdagent_contracts/step_inputs.py`
  (`resolve_data_inputs`, `resolve_analysis_inputs`): same user, type/schema, hash, snapshot, semantic version, one
  common dataset, Compare → PeerDefinition lineage.
- The Orchestrator forwards a ref only after `artifact_get` confirms type, hash, snapshot, semantic and status
  `VALID` / `PARTIAL`. `run_state@1` is versioned before execution, after each wave and at the end.
- Types: `dataset` / `metric` / `dq` (Data), `insight` (Insight), `peer_definition` / `comparison` (Compare),
  `chart_spec@1` (Chart, `bindings[]` with `source_ref`), `report@1` (Report), `run_state@1` (Orchestrator).
- Every `chart_spec.payload.vega_lite` must pass `vdagent_contracts.vega_lite.validate_vega_lite` (Vega-Lite v6);
  Chart does not store a failing spec and Report rejects one. `kpi_card` renders as a `text` mark.
- Report re-resolves every statement and chart binding before saving; any mismatch → `EVIDENCE_INVALID`, and neither
  `rp_…` nor `report@1` is written. Reports embed charts as `{{chart_spec:<id>@<version>}}`.
- Out-of-scope rows are never counted or reported (`re_run_query` has no hidden-row count).

Details: [docs/contracts/data-contract.md](docs/contracts/data-contract.md),
[docs/contracts/agent-contract.md](docs/contracts/agent-contract.md).

## 9. Testing commands

```bash
uv sync
uv run pytest -q -p no:cacheprovider                 # host suite (testpaths: backend/tests, contracts, agents)
make docker-test                                     # same suite in the test image, no network
cd frontend && npm test && npm run build             # Vitest + tsc + vite
make secret-check                                    # secret scan
git diff --check
make warehouse-check                                 # read-only AWS preflight (snapshot, semantic, unit count)
make up && make status                               # product on :8000 against AWS (make restart, make build, make logs)
make mock-up / make mock-down                        # explicit SQLite mock on :8001
acceptance/ws7/run.sh                                # mock acceptance: REST golden, lineage, restart, browser
```

- Offline runs: `env -u VDAGENT_RE_WAREHOUSE_DB INSIGHT_LLM=off COMPARE_LLM=off uv run --frozen pytest -q -p no:cacheprovider`.
- Real-DW tests skip without `VDAGENT_TEST_PG_DSN`; live-LLM tests skip without keys.
- Acceptance browser step needs a Python with Playwright in `WS7_BROWSER_PYTHON`; it is skipped otherwise.
- `uv` installed as a snap cannot write files under `/tmp`: pipe its output and put `WS7_OUT` outside `/tmp`.
- Other agents' tests import fixtures from `vdagent_data.tests` and `vdagent_data.steps`; keep those import paths.
- Golden cases and expected values: [docs/testing/e2e-golden.md](docs/testing/e2e-golden.md).

## 10. Security and secret rules

- No secret in Git, logs, artifacts, documents or test output. `.env` files are gitignored; templates are
  `.env.example`. Committed real `.env*` files are reported by the scanner without being read.
- `make secret-check` runs `scripts/check_secrets.py` (standard library only) over the files Git would commit: six
  patterns (private key, GitHub token, AWS access key, provider `sk-…` key, Slack token, URL with a 12+ character
  password); template passwords allowed; output `<file>:<line>: <rule> [REDACTED]`; exit 0 PASS / 1 findings /
  2 incomplete. Tests: `backend/tests/test_check_secrets.py`.
- If a secret was committed: rotate it first, tell the maintainer, then remove it from history with an approved tool
  ([GIT_RULE.md §9](GIT_RULE.md)).
- Warehouse access is read-only (`vdagent_reader`); nothing in the repo writes to AWS; no destructive migration runs
  automatically.
- **Authentication is not implemented (F-05, BLOCKED).** `X-User-Id` is a dev-only header; the system is not
  production-ready. Decisions AUTH-1…5: [docs/security/auth-design.md](docs/security/auth-design.md). Cross-user
  access to reports, chart specs and tasks returns 404; a missing user or MCP token returns 401.

## 11. Current blockers

| Id | Blocker | Effect |
|---|---|---|
| F-05 | No authentication; `X-User-Id` trusted | not production-ready |
| B-11 | No approved peer rule; Compare selects its own set (5 in the mock, 13 for `MAS-U03832`); the mock DW's stored `dw_peer_n = 7` cannot be reproduced | peer-set acceptance and 7-peer chart tests skipped |
| B-2 | `min_group_size` PENDING in `sc-1` vs Compare `min_peer_count` | Compare runs with default 5, flagged `BLOCKED:B-2_min_peer_count` |
| D2b | Segment mapping `HIGH_END` / `MID_END` → Insight enum | Insight `segment` field |
| B-3 | Mock `net_area_m2` is synthetic (`area_m2 × 0.92`) | sign-off of mock peer results |
| B-12 | Insight `sc-1` action codes, templates and thresholds lack an approved source | Insight wording on the mock |

Data limits on the real warehouse: the `re` view layer hides `discount_pct`, `is_overdue_flag`,
`asking_price_per_m2`, `subsidy_duration_mo` (reported as missing, so runs usually end `partial`); `dw_peer_n` does not
exist. Owners and next actions: [docs/architecture/decisions.md](docs/architecture/decisions.md).

## 12. Current verified status (Full System Final Verification, 2026-10-04)

Verified on `main` @ `aed2917` + the staged Phase 1–5 change set; Phase 6A changed documentation only and re-ran the
offline checks (results below).

| Check | Result |
|---|---|
| Host `uv run pytest -q -p no:cacheprovider` | **0 failed / 1965 passed / 52 skipped** (2,017 collected) |
| `make docker-test` | **0 failed / 1965 passed / 52 skipped** |
| Frontend `npm test` / `npm run build` (tsc + vite) | 31/31 PASS / PASS |
| `make secret-check` | PASS (0 findings) |
| `uv lock --check` | PASS |
| `make warehouse-check` | `SNAP-20260630-01` APPROVED, `3.1.0`, 47,713 units |
| `make up` / `make status` / API | healthy; 6 plugins; log `Warehouse backend: PostgreSQL`; `/api/users`, `/api/agents`, `/api/tasks`, `/api/reports` 200 |
| Live six-agent E2E on AWS (`MAS-U03832`, Alice) | all 6 completed; B2 ∥ B3; 19/19 hashes; one snapshot/semantic/dataset; B2.in == B3.in == B1.out; 13 peers; 53,449,321 vs 52,577,623 VND/m² (+1.66 %); `SEVERE_PHYSICAL_DEFECT`, `LOW_SALES_INCENTIVE`; 6 valid chart specs, 35/35 bindings; 46/46 statements; 6 sections; provenance PostgreSQL `cdw` |
| Mock golden (`make mock-up`, A12-08) | DOM 138 vs 61; gap 12.40 %; 5 peers; `OVERPRICED_VS_PEER`; provenance SQLite |
| `acceptance/ws7/run.sh` | REST 4/4, lineage 7/7, restart 2/2; browser SKIPPED (no Playwright) |
| Failure injection | missing / empty / bad-scheme / host-less DSN → exit 1 `ReWarehouseConfigError`; explicit mock → starts with WARNING; unreachable AWS → `SqlError` |

Skips (52) are environmental: missing data packs, live keys, real-DW DSN, and the two B-11 tests.

**Not verified:** authentication (F-05), production deployment, LLM phrasings beyond the validated happy cases,
follow-up turns, per-worker timeouts, the Report LangGraph/Jev direct-chat path with a live judge.

Remaining debt: browser acceptance needs Playwright; no frontend linter; Git history still holds removed data (no
history rewrite).

## 13. Canonical documents and documentation policy

| Topic | Document |
|---|---|
| Onboarding, Quick Start, `make` targets | [README.md](README.md) |
| Documentation index and ownership rules | [docs/README.md](docs/README.md) |
| Architecture | [docs/architecture/system.md](docs/architecture/system.md) |
| Decisions and blockers | [docs/architecture/decisions.md](docs/architecture/decisions.md) |
| Data contract / agent contract / warehouse v3.1.0 | [docs/contracts/data-contract.md](docs/contracts/data-contract.md), [docs/contracts/agent-contract.md](docs/contracts/agent-contract.md), [docs/contracts/warehouse-v3.1.0.md](docs/contracts/warehouse-v3.1.0.md) |
| Orchestrator, Report design | [docs/agents/orchestrator.md](docs/agents/orchestrator.md), [docs/agents/report.md](docs/agents/report.md) |
| Agent runbooks | `agents/<name>/README.md` (e.g. [agents/data/README.md](agents/data/README.md)) |
| E2E golden and acceptance | [docs/testing/e2e-golden.md](docs/testing/e2e-golden.md) |
| Authentication design | [docs/security/auth-design.md](docs/security/auth-design.md) |
| Git and warehouse data rules | [GIT_RULE.md](GIT_RULE.md) |
| History (status log to 2026-10-04, archive) | [docs/archive/agents-history-2026-09.md](docs/archive/agents-history-2026-09.md), [docs/archive/](docs/archive/README.md) |

Documentation policy:

- `AGENTS.md` keeps only rules and the current verified state. Do not append progress logs here; record dated evidence
  in the relevant canonical document or under `docs/archive/` and update §12 in place.
- One canonical document per topic; other files summarise and link. Historical documents keep their banner and are
  not updated to describe the current system.
- Historical docs live under [docs/archive/](docs/archive/README.md) (legacy TypeScript platform, 2026-09 integration
  and evidence, refactor plan, legacy agent contracts, dated design specs). The archive is **not** a source of truth.
- `docs/product/VDAgent_API_Contract_FE_v0.3_OpenAPI.docx.pdf` is an unimplemented FE API draft (`/api/v1/...`), not the
  current API; its future is a product/FE owner decision.
