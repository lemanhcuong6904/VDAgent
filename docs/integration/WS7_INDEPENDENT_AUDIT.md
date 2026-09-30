# WS7 Independent Audit — VDaAgent six-agent system

Audit date: 2026-09-30. Branch `agent_a/debug` @ `4b420e9` with a large uncommitted / untracked working tree
(172 status entries; nothing committed, nothing reset). Auditor re-executed every result in this document; earlier
reports were used only as claims to check. Evidence files: [ws7_audit_evidence/](ws7_audit_evidence/).

Status labels: **PASS** (executed and met), **FAIL** (executed and not met), **BLOCKED** (needs a business decision),
**NOT VERIFIED** (could not be executed in this audit, reason given).

## 1. Executive summary

- **WS7 was not implemented.** No WS7 acceptance suite, browser test or acceptance document existed; root
  `AGENTS.md` §16 and `E2E_TEST_PLAN.md` both state "WS7 has not started / PLANNED". This audit therefore evaluates
  the system against the WS7 acceptance criteria directly (finding F-06).
- The **six-agent deterministic offline flow works**: one REST message to the Orchestrator ran Data → [Insight ∥
  Compare] → Chart → Report in an isolated Docker backend; all analytical values match the golden expectations; every
  chart binding (18/18) and report statement (28/28) resolves to its exact source value; one dataset roots all lineage;
  no PRJ-Y data leaked; cross-user REST access returns 404.
- **The report does not fully render in a real browser:** 2 of 5 embedded charts (the KPI cards) fail with a
  Vega error because Chart emits `mark: "kpi_card"`, which is not Vega-Lite (F-01, HIGH). No existing test renders a
  chart spec, so the 1139-test suite does not see it.
- Reliability gaps: failed runs are reported as `task.status = completed` (F-03); a crashed run leaves `run_state`
  stuck at `running` with no reconciliation (F-04); superseded artifact versions cannot be re-verified by hash because
  the hash covers the mutable `status` (F-02).
- Production blockers: no authentication (identity = trusted `X-User-Id` header, F-05); live LLM / Jev paths are
  unverified. Business blockers B-11, B-2, D2b, B-3, B-12 are unchanged and remain BLOCKED.

## 2. Acceptance matrix

| # | Criterion | Result | Evidence |
|---|---|---|---|
| A1 | One user message triggers the whole DAG (no manual REST chaining) | PASS | [golden_run.txt](ws7_audit_evidence/golden_run.txt): task `t_7eac4e6a6fe3`, 6 invocations |
| A2 | Dependencies enforced by code | PASS (code + tests) | `agents/orchestrator/vdagent_orchestrator/dag.py`, `executor.py`; `agents/orchestrator` 53 PASS |
| A3 | Insight ∥ Compare run concurrently | PASS | runtime: insight 01:14:48.333–.425, compare .349–.443 (overlap); barrier tests in `test_dag.py`, `test_ws5_golden.py` |
| A4 | B2 and B3 receive identical pinned B1 refs | PASS | run_state `art_d73a669884c5`: `B2.in == B3.in == B1.out` |
| A5 | Chart consumes current-run Insight/Compare artifacts | PASS | lineage: all chart_spec reach the run's dataset; no demo ids |
| A6 | Report consumes real upstream + verified chart_spec | PASS | report `validation`: 28 statements, 18 bindings, 5 charts checked |
| A7 | run_state records execution and partial failures | PASS (normal runs) / FAIL (after crash, F-04) | [golden_lineage.txt](ws7_audit_evidence/golden_lineage.txt), [restart.txt](ws7_audit_evidence/restart.txt) |
| A8 | No fallback to demo / stale / fabricated data | PASS | payload scan: no `run_vhop_demo`, `metric_dom_target`, `synthetic_` |
| A9 | Snapshot SNAP-2026-09-28 / sc-1 on every artifact | PASS | lineage audit |
| A10 | DOM 138 vs peer median 61 | PASS | comparison `art_931c382ec6eb` |
| A11 | Net price 72,500,000 vs 64,500,000 VND/m²; gap 12.40 % | PASS | comparison (`pctGap` "12.4", rendered 12,40 %) |
| A12 | Compare selects five peers | PASS (observed: A12-11, A10-02, A14-03, B09-05, B11-07) | peer_definition `art_1d44965ab541` |
| A13 | Seven-peer golden set | **BLOCKED (B-11)** | two tests skipped with the B-11 reason |
| A14 | Artifacts: ownership, schema, version, hash, lineage | PASS for current versions; **FAIL** for re-verification of superseded versions (F-02) | lineage audit: 5 superseded run_state versions per run fail hash recomputation |
| A15 | Every downstream artifact reaches the one dataset | PASS | `all non-run_state artifacts reach the one dataset: True`, no dangling refs |
| A16 | Chart bindings / report statements resolve exactly | PASS | 18/18, 28/28 |
| A17 | No PRJ-Y data | PASS | payload scan; dataset `hidden_rows` 28 (see F-08) |
| A18 | Six report sections, ≥ 2 charts/tables | PASS (data) | 6 sections, 5 charts, 2 tables |
| A19 | Report charts render in a real browser | **FAIL** (3/5) | [browser_log.json](ws7_audit_evidence/browser_log.json), [04_chart_4.png](ws7_audit_evidence/04_chart_4.png) — F-01 |
| A20 | No raw `{{chart_spec…}}` tokens in the viewer | PASS | `raw_embed_tokens_in_report: false` |
| A21 | Actions evidence-based or insufficiency stated | PASS | 0 actions; note "Chỉ có 0 đề xuất được Insight hỗ trợ…" |
| A22 | Report delivered via REST (`/api/reports/{id}`) | PASS | Alice 200, Bob 404 |
| A23 | Cross-user access to report / chart_spec / task | PASS (404) | [authz_probe.txt](ws7_audit_evidence/authz_probe.txt) |
| A24 | Unauthenticated REST / MCP | PASS (401) for missing/unknown user and token | authz probe |
| A25 | Real authentication of users | **FAIL for production** (F-05) | `X-User-Id` header is the only identity |
| A26 | Tampered hash, wrong type, missing deps, snapshot/semantic mismatch, invalid bindings, unsupported claims, unauthorized MCP ops | PASS (test level) | groups in §7; not re-exercised at runtime |
| A27 | Concurrent requests of two users | PASS | [concurrency.txt](ws7_audit_evidence/concurrency.txt), [concurrency_lineage.txt](ws7_audit_evidence/concurrency_lineage.txt) |
| A28 | Failed runs not reported as successful | **FAIL** (F-03) | Bob's run: answer "Không hoàn thành…", `task.status = completed` |
| A29 | Restart / crash recovery | PARTIAL: task marked `failed: backend restarted` (PASS); run_state stale, no resume (FAIL, F-04) | restart.txt |
| A30 | Idempotent retry | PASS within one task (unit); duplicate user messages create new full runs (F-11) | `test_repeated_*`; concurrency run |
| A31 | Timeout and cancellation | PASS (unit); NOT VERIFIED at runtime (runs finish in < 1 s; no slow fixture) | `test_timeout_*`, `test_report_timeout_*` |
| A32 | Chat Mode stops after B4 / explain-only plan | PASS | "Vì sao căn A12-08 bán chậm?" → orchestrator, data, insight |
| A33 | AgentCatalog = implemented operations | PASS | `test_catalogs_declare_the_implemented_operations`, `test_report_catalog_matches_the_implementation` |
| A34 | Live LLM / Jev behaviour | NOT VERIFIED (not allowed: paid/external) | — |
| A35 | WS7 acceptance suite exists | **FAIL** (F-06) | no files; docs say PLANNED |

## 3. Golden case reproduction (six agents)

Environment: isolated compose project `vdagent_ws7audit`, volume `vdagent_ws7audit_var`, port 8021
([audit-compose.yml](ws7_audit_evidence/audit-compose.yml)); plugins loaded: orchestrator, data, compare, insight,
report, chart; DW checksum `523af4c6a963a2ed`, latest APPROVED `SNAP-2026-09-28`; demo scopes seeded.

Request (one `POST /api/agents/orchestrator/messages`, user `u_000000000001`):
"Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."

| Item | Observed |
|---|---|
| Task | `t_7eac4e6a6fe3`, completed in 0.83 s |
| Invocations | orchestrator `inv_566f77a24400`; data `inv_d46ccf21c796` (.954–.290); insight `inv_1bb291b46f85` (.333–.425) ∥ compare `inv_8ff512749f81` (.349–.443); chart `inv_e1fe5ff0ff72`; report `inv_cfb00543f10f` |
| run_state | `art_d73a669884c5` v6, `partial`, waves [[B1],[B2,B3],[B4],[B5]], all steps completed |
| Data | dataset `art_a72e66436394` (VALID), metric `art_7573e3816270`, dq `art_84be46ac0b88` |
| Insight | `art_23cddba212d7` (`OVERPRICED_VS_PEER`, bindings 138 / 12.40) |
| Compare | peer_definition `art_1d44965ab541` (5 peers, net area 63.02, ratio 0.10 → 10.00 %), comparison `art_931c382ec6eb` |
| Chart | 5 chart_spec: bar ×2, scatter, kpi_card ×2 |
| Report | `art_8f9930582ac1` (report@1, PARTIAL), delivered `rp_df42da5b27f5`; 6 sections, 28 statements, 5 charts, 2 tables |
| Limitations carried | B-2, D2b, CONFIG_PENDING:min_group_size, DQ_MISSING:asking_price_vnd:12, FIELD_UNAVAILABLE:asking_price_per_m2, METRIC_UNAVAILABLE:discount_pct / subsidy_duration_mo, SYNTHETIC_SOURCE:net_area_m2, WINDOW_INCOMPLETE:inquiry_leads_30d:3 |

## 4. Data correctness, lineage and security

- Snapshot/semantic enforcement, TEXT keys, scope, net-area-only peers, explicit tolerance conversion, Decimal
  strings, null + limitation for missing metrics, incomplete funnel window: verified by the Data/WS3 suites (46 + 24
  PASS) and by the golden artifacts (e.g. `inquiry_leads_30d` null with `WINDOW_INCOMPLETE:…:3`).
- Five-peer vs seven-peer: the engine's level-0 pool is same project + same launch batch LB-02 + orientation group +
  floor band MID; B15-02 (LB-03) and C05-02 (LB-01) never enter the pool, A06-01 (LOW) is excluded. No sc-1 rule
  explains the DW's 7 (`peer_n`). Unchanged; B-11 BLOCKED.
- No causal overclaim found: Insight text uses "yếu tố có khả năng liên quan"; the report adds "không phải kết luận
  nhân quả".
- Security probes (runtime): cross-user report/chart_spec/task → 404 without leaking existence details; missing or
  unknown `X-User-Id` → 401; MCP without/with a bogus token → 401; Bob cancelling Alice's task → 404; Bob's golden
  request → `UNIT_NOT_FOUND`, only a run_state written. Error texts do not echo other users' data.
- F-08: Data stores `hidden_rows.dim_unit_master = 28` in the user's dataset — the count of out-of-scope units
  (other projects) is disclosed to the user.

## 5. Reliability, concurrency, recovery

- 4 concurrent requests (Alice ×2 report mode, Bob, Alice chat mode): all finished, per-run lineage isolated (each run
  its own dataset, 18/18 + 28/28 each). Same-user Data steps are serialized by the engine's per-(user, agent) stack —
  expected semantics.
- Crash (`docker kill -s KILL` right after the request) + restart: task `t_f4465d389b2a` → `failed`, orchestrator
  invocation `failed: backend restarted` (honest). But its run_state stays `running` with all steps `pending`
  (F-04). "Idempotent resume" only applies when the same task is re-invoked, which the API never does (a new message
  is a new task) — so automatic recovery does not exist at runtime.
- Failure semantics: Bob's failed run and partial runs have `task.status = completed` (F-03); the truth is only in
  run_state and the answer text.

## 6. Browser and report rendering (real browser)

Playwright 1.63 (isolated venv) driving the system Google Chrome, headless, against the audit backend; script
[browser_golden.py](ws7_audit_evidence/browser_golden.py). Flow: open UI → select orchestrator → type the golden
question → Enter → wait for the answer → click the `rp_…` link → inspect the report.

| Check | Result |
|---|---|
| Answer appears (0.92 s) with 138, 61, 72.500.000, 64.500.000, 12,40, B-11 | PASS ([02_chat_answer.png](ws7_audit_evidence/02_chat_answer.png)) |
| `rp_…` link visible and opens the report | PASS |
| Six section headings | PASS ([03_report.png](ws7_audit_evidence/03_report.png)) |
| Raw `{{chart_spec…}}` tokens | none (PASS) |
| Charts rendered as SVG | **3 of 5** — bar ×2 ([04_chart_1.png](ws7_audit_evidence/04_chart_1.png)), scatter ([04_chart_3.png](ws7_audit_evidence/04_chart_3.png)); both KPI cards fail: "Chart failed to render: Cannot read properties of undefined (reading 'filled')" ([04_chart_4.png](ws7_audit_evidence/04_chart_4.png)) — **FAIL (F-01)** |
| Page errors / failed requests | none; console: 5 × "input spec uses Vega-Lite v5, current is v6.4.3" warnings (F-09) |

## 7. Test execution summary (all executed by the auditor)

| Command | Result |
|---|---|
| `uv run pytest -q -p no:cacheprovider -rs` (host) | 1139 passed, 29 skipped, 14 subtests passed |
| `docker compose --profile test build tests && docker compose --profile test run --rm tests python -m pytest -q -p no:cacheprovider -rs` | 1139 passed, 29 skipped, 14 subtests passed |
| Frontend (copy in scratch, `node:22-slim`): `npm ci && npm run build && npm test` | build PASS; Vitest 2 files, 8 tests PASS |
| `uv run pytest -q backend/tests/test_mcp_server.py backend/tests/test_mcp_artifacts.py backend/tests/test_mcp_re_tools.py backend/tests/test_artifact_store.py backend/tests/test_seed_scopes.py backend/tests/test_api.py` | 69 passed |
| `uv run pytest -q contracts` | 75 passed |
| `uv run pytest -q agents/data` | 46 passed |
| WS3 files (insight/compare dw_integration, ws3_cross_agent, ws3_plugins) | 24 passed, 1 skipped (B-11) |
| `uv run pytest -q agents/chart/vdagent_chart/tests/test_ws4_integration.py` | 13 passed, 1 skipped (B-11) |
| `uv run pytest -q agents/orchestrator` | 53 passed |
| `uv run pytest -q agents/report` | 39 passed |
| Runtime golden (Docker, one request) | PASS (values, lineage) |
| Real-browser golden (Chrome + Playwright) | FAIL on chart rendering (3/5) |
| `git diff --check` | clean |

Skips (29) match the WS6 baseline: Insight export pack absent 11, Compare VHOP pack absent 13, live keys absent 3,
B-11 2. Compare skips are reported under `../../Check_Version/…` because of stale untracked `__pycache__` compiled from
another checkout (F-10); the executed code is this repository's. Host has no `frontend/node_modules`, so the frontend
was built/tested from a copy in a container.

## 8. Defect register

| ID | Sev | Finding | Reproduction | Expected / observed | Root cause | Recommended fix + regression test | Status |
|---|---|---|---|---|---|---|---|
| F-01 | HIGH | KPI chart_specs are not valid Vega-Lite; 2/5 report charts fail in the browser | §6 script; `GET /api/chart-specs/<kpi id>/1` shows `mark.type: "kpi_card"` | all embedded charts render / 3 of 5 render | `agents/chart/vdagent_chart/vega.py` `build_vega_spec` maps unknown chart types to the mark name; Report `validate_chart` only checks the `$schema` prefix | emit a valid Vega-Lite KPI (e.g. `text` mark) or exclude non-renderable types; validate specs with the Vega-Lite compiler in Chart/Report tests; add a browser test | FIXED, VERIFIED (§12) |
| F-02 | MEDIUM | Superseded artifact versions fail hash recomputation | `lineage_audit.py`: run_state v1–v5 mismatch in every run | stored hash verifiable / not verifiable after supersede | `ArtifactEnvelope.compute_content_hash` includes `status`; the store's only allowed update sets `status = SUPERSEDED` | exclude `status` from the content hash (versioned migration) or store the hash of the original draft explicitly; test recomputation after supersede | FIXED, VERIFIED (§12) |
| F-03 | MEDIUM | Failed / partial DAG runs are reported as `task.status = completed` | Bob's golden request (`t_1896e0f58544`) | failed / completed | engine status = orchestrator turn outcome; run outcome only in run_state + answer | expose run outcome (e.g. task field or AgentReport of the root) and have the UI/API show it; test failed-run status | FIXED, VERIFIED (§12) |
| F-04 | MEDIUM | Crash leaves run_state `running`; no reconciliation or resume | kill backend right after a request (restart.txt) | run_state terminal after restart / stuck `running` | executor persists only while running; engine recovery does not touch artifacts; resume keyed by task id | reconcile run_state on startup (mark `aborted`) and/or allow an explicit resume; restart test | FIXED (reconcile to `interrupted`; no auto-resume), VERIFIED (§12) |
| F-05 | HIGH (production) | No authentication: identity is the `X-User-Id` header | any client sets the header | authenticated user / trusted header | PoC design (`backend/vdagent_backend/api/deps.py`) | real auth before any non-local deployment | BLOCKED: design + decision request in [AUTH_DESIGN.md](AUTH_DESIGN.md) |
| F-06 | MEDIUM | WS7 acceptance suite and browser test do not exist | repo search | WS7 implemented / docs say PLANNED | not started | add an automated acceptance + browser suite (this audit's scripts are a starting point) | FIXED, VERIFIED: `acceptance/ws7/` (§12) |
| F-07 | LOW | Documentation contradictions about WS6/WS7 status | AGENTS.md §0.4 (WS6 PLANNED) vs §16 (IMPLEMENTED); master plan header "WS6–WS7 PLANNED" vs its WS6 evidence | consistent / inconsistent | addendum not reconciled | fixed in this audit's doc update | RESOLVED (docs updated) |
| F-08 | LOW | Out-of-scope row count disclosed (`hidden_rows`) | dataset payload | count hidden or policy-approved / 28 disclosed | `count_hidden=True` in Data | decide policy; drop or coarsen the count | FIXED, VERIFIED (§12) |
| F-09 | LOW | Chart specs declare Vega-Lite v5 while the UI uses v6.4.3; titles hard-code "— VHop" and English question names | browser console; chart titles | consistent / warnings, mixed-language titles | Chart `VEGA_SCHEMA`, service title | align schema version; localized titles | FIXED, VERIFIED (§12) |
| F-10 | LOW | Stale `__pycache__` from another checkout mislabels test paths | `pytest -rs` | repo paths / `../../Check_Version/...` | untracked `.pyc` | delete stale caches | FIXED (52 stale .pyc removed; 0 remain) |
| F-11 | LOW | Duplicate identical requests create full new runs and reports | concurrency run (2 Alice report runs) | documented behaviour / duplicates | idempotency is per task only | document or add request-level dedup | FIXED, VERIFIED: `Idempotency-Key` (§12) |

No CRITICAL finding: no wrong business number, no lineage corruption, no cross-user leak was observed.

## 9. Business blockers (unchanged, owner decisions required)

| ID | Open question | Evidence | Affects | Owner | Tests to add after the decision |
|---|---|---|---|---|---|
| B-11 | Which rule selects the 7 golden peers (batch/zone/similarity)? | engine selects 5 at level 0; hard filters give 8 in LB-01..03 incl. C05-02 (similarity 0.7948 > B15-02 0.5758) | Compare, Chart, Report, golden acceptance | Integration Owner + DATA owner | un-skip `test_golden_peer_set_is_the_seven_canonical_peers`, `test_golden_seven_peer_chart` |
| B-2 | Approved `min_peer_count` / relation to `min_group_size` (PENDING 5 in sc-1) | Compare uses engine default 5, marks `BLOCKED:B-2_min_peer_count` | Compare sufficiency, Report wording | DATA owner / Sales Ops | Compare sufficiency tests with the approved value |
| D2b | Mapping HIGH_END/MID_END ↔ Insight segment enum | raw segment kept, `BLOCKED:D2b_segment_mapping` | Insight market context | DATA owner | Insight ProjectRow / T5 tests |
| B-3 | Business meaning of `net_area_m2` (fixture = area × 0.92) | `SYNTHETIC_SOURCE:net_area_m2` on every run | Data, Compare peer band, Report | DATA owner | Data/Compare tests on real net areas |
| B-12 | Canonical Insight action codes / templates / Insight-only thresholds for sc-1 | `semantic_insight.sc-1.yaml` provenance header | Insight wording and recommendations (0 actions in golden) | Sales Ops / DATA owner | Insight config + recommendation tests |

## 10. Readiness by scope

| Scope | Assessment |
|---|---|
| Deterministic offline demo (Docker, `*_LLM=off`) | Ready with caveat: numbers and lineage are correct; fix F-01 before showing the report view (2 KPI charts error). |
| Live-LLM integration | Not verified (no keys, paid/external services not allowed). Orchestrator/Data/Report LLM paths only covered by fake-LLM unit tests. |
| Production deployment | Not ready: F-05 (no auth), F-03/F-04 (status and recovery), B-11/B-2/D2b/B-3/B-12 open, live paths unverified. |

## 11. Reproducible commands

```bash
S=docs/integration/ws7_audit_evidence
AC="docker compose -p vdagent_ws7audit -f docker-compose.yml -f $S/audit-compose.yml --profile offline"
$AC build backend-offline && $AC up -d backend-offline             # isolated stack on :8021
curl -s -X POST -H 'X-User-Id: u_000000000001' -H 'Content-Type: application/json' \
  localhost:8021/api/agents/orchestrator/messages \
  -d '{"content":"Vì sao căn A12-08 bán chậm? So sánh với các căn tương đồng, vẽ biểu đồ và xuất báo cáo."}'
docker cp $S/lineage_audit.py vdagent_ws7audit-backend-offline-1:/tmp/l.py
docker exec vdagent_ws7audit-backend-offline-1 python /tmp/l.py <task_id>      # hashes, lineage, bindings, statements
python3 -m venv /tmp/pw && /tmp/pw/bin/pip install playwright               # uses the system Chrome (channel="chrome")
/tmp/pw/bin/python $S/browser_golden.py /tmp/out                            # real-browser golden
$AC down && docker volume rm vdagent_ws7audit_var                           # audit resources only
```

## 12. Remediation (2026-09-30)

All code changes were developed test-first: a RED test that reproduces the finding, then the fix.
Nothing was committed or pushed.

| Finding | Root cause | Fix | Regression tests |
|---|---|---|---|
| F-01 | `vega.py` used the chart type as the mark; the semantic channels (`label`/`value`/`reference`/`series`…) were copied into Vega-Lite; Report checked only `$schema` | `project_encoding` maps every allowed chart type to a real mark and real channels (KPI = `text` mark with fixed height); shared `vdagent_contracts/vega_lite.py` `validate_vega_lite` (mark, channels, types, fields in data); Chart refuses to store an invalid spec (`INVALID_VEGA_LITE`); Report `validate_chart` rejects it (`EVIDENCE_INVALID`) | `contracts/.../test_vega_lite.py`, `chart/.../test_vega.py` (all 17 allowed types), `test_ws4_integration.py` (golden specs valid; malformed projection never stored), `report/.../test_ws6_report.py` (3 malformed specs) |
| F-02 | The hash covers `status`, and SUPERSEDED rewrites status | `artifact_store.verify(envelope)` recomputes with the status at write time for SUPERSEDED rows. History and stored hashes are unchanged | `backend/tests/test_ws7_remediation.py` (current, superseded, tampered) |
| F-03 | Task status = orchestrator turn status | `TurnContext.report_outcome`, `tasks.outcome` (`completed`/`partial`/`failed`/`interrupted`); a failed run gives task `failed`; UI shows `completed · partial` | backend and orchestrator tests, Vitest `taskStatus.test.ts` |
| F-04 | Recovery ignored run_state artifacts | On startup, a new run_state version is written (`interrupted`, running/pending steps → `interrupted`, reason `backend restarted`). **No automatic resume**: steps call external agents, and replaying them is not proven idempotent. The user re-asks | `test_restart_reconciles_running_run_states`; acceptance kill -9 test |
| F-05 | PoC header identity | Not implemented: [AUTH_DESIGN.md](AUTH_DESIGN.md), decisions AUTH-1…5 | n/a |
| F-06 | No suite | `acceptance/ws7/run.sh`: fresh isolated stack (project `vdagent_ws7acc`, port 8021, own volume, torn down) → REST golden → real browser → store audit → kill -9/restart | 14 acceptance tests |
| F-08 | Data asked `re_run_query(count_hidden=true)` and stored the count | Data no longer counts; the backend tool no longer offers `count_hidden` (refused if sent) | `test_steps.py`, `test_mcp_re_tools.py` |
| F-09 | v5 schema; `— VHop` title | v6 schema (Chart and backend `create_chart`); Vega title = the Vietnamese view title; frontend `autosize: fit-x` | chart and backend tests; browser console 0 messages |
| F-10 | `.pyc` from another checkout | Deleted only those 52 files (detected via `co_filename`); none tracked | re-scan: 0 |
| F-11 | No request key | `Idempotency-Key` header: same user + agent + key returns the same task (`200`, `deduplicated: true`); a different content returns `409 idempotency_conflict`; identical text without a key is **not** merged | backend tests; acceptance golden |

### Acceptance rerun (fresh offline Docker, one request)

`acceptance/ws7/run.sh` gave **PASS**, with 14/14 tests. Evidence is in
[ws7_remediation_evidence/](ws7_remediation_evidence/).

- **Golden run.**
  - Task `completed / partial`, with six invocations (orchestrator, data, insight, compare, chart, report).
  - Pinned to SNAP-2026-09-28 and sc-1.
  - DOM 138 vs 61; 72,500,000 vs 64,500,000 VND/m²; 12.40%; 5 peers.
  - B-11 is stated in the answer.
- **Store checks.**
  - Every artifact version verifies against its stored hash, including SUPERSEDED run_state versions.
  - One dataset. All lineage reaches it through pinned hashes.
  - 5 chart_specs pass `validate_vega_lite`, and their bindings resolve.
  - 28/28 report statements resolve.
  - No PRJ-Y, D12-09 or `hidden_rows`.
- **Report API.** Alice gets 200; Bob gets 404; a request without identity gets 401.
- **Real browser** (Chrome via Playwright). The report shows 5 figures with 5 rendered SVGs. There are 0 console
  messages, 0 page errors and no raw `{{chart_spec}}` tokens. Screenshots `03_chart_1..5.png`.
- **Kill -9 mid-run, then restart.** Task `failed / interrupted`; invocations `backend restarted`; run_state
  `running` → `interrupted`.
- **Regression.**
  - Host 1196 passed / 29 skipped; Docker test image 1196 passed / 29 skipped.
  - Frontend build PASS, Vitest 10 passed.
  - `git diff --check` clean.

### Still open

- F-05: authentication is BLOCKED on owner decisions.
- Business blockers B-11, B-2, D2b, B-3 and B-12 are unchanged. B-11 stays BLOCKED: 5 peers, and no seven-peer rule
  was invented.
- Live LLM and Jev paths are NOT VERIFIED.
- **The system is not production-ready.**
