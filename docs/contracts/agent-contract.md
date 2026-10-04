# Agent Contract Matrix

Status: architecture **APPROVED** (D1–D10, 2026-09-30); operations of §3 are PLANNED (WS2–WS6) except the Chart
MCP permissions (IMPLEMENTED, WS1). Date: 2026-09-30. Data semantics: [data-contract.md](data-contract.md).

## 1. Transport (reuse, no new mechanism)

| Layer | Existing piece | Evidence | Use in target flow |
|---|---|---|---|
| Call | `send_to_agent` → `ctx.call_agent(tool_call_id, target, message)` → peer reply text | [sdk/__init__.py:149-185](../../sdk/vdagent_sdk/__init__.py#L149), [runtime/engine.py](../../backend/vdagent_backend/runtime/engine.py) | Unchanged |
| Request body | `StepSpec@1` JSON (a message starting with `{` is a contract request) | [messages.py:35-45,56-81](../../contracts/vdagent_contracts/messages.py#L56) | Every orchestrator → worker call |
| Reply body | `AgentReport@1` JSON | [reports.py:54-71](../../contracts/vdagent_contracts/reports.py#L54) | Every worker → orchestrator reply |
| Data exchange | Artifact store via MCP `artifact_put/get/list` | [mcp/handlers.py](../../backend/vdagent_backend/mcp/handlers.py), [artifacts/envelopes.py](../../backend/vdagent_backend/artifacts/envelopes.py) | All analytical payloads (no data inside messages) |
| Planning metadata | `AgentCatalog` / `CatalogOperation` (`requires` = HARD wait, `uses_if_present` = SOFT) | [catalog.py:17-33](../../contracts/vdagent_contracts/catalog.py#L17) | Orchestrator DAG |
| Errors | `ErrorClass` (10 classes) | [errors.py](../../contracts/vdagent_contracts/errors.py) | `AgentReport.error.code` → class via catalog `error_codes` |

Free text remains supported by every agent as a fallback (`parse_incoming` → `FreeText`), but the target flow uses
contract messages only. Backend change **done in WS1**: `chart` added to the agent grants (today: per-plugin `mcp_tools` in [backend/config.yaml](../../backend/config.yaml)); `WRITABLE_TYPES` ([mcp/handlers.py](../../backend/vdagent_backend/mcp/handlers.py)) allows `chart: {chart_spec}`.

## 2. Common request / reply rules

`StepSpec@1` fields used (existing model):
`run_id` (= Backend task id), `plan_id`, `step_id` (`B<n>`), `idempotency_key = plan_id:step_id`, `operation`,
`spec` (per operation, §3), `user_context` (from MCP `get_user_context`, never from the question),
`snapshot_id` (APPROVED), `semantic_config_version`, `input_refs[ArtifactRef]`, `released_inputs`, `deadline_s`,
`original_question`.

`AgentReport@1` reply rules (PROPOSED_NEW usage):

| State | When | Required fields |
|---|---|---|
| `completed`, `partial=false` | all outputs VALID | `artifact_refs` ≥1, `snapshot_id`, `semantic_config_version` |
| `completed`, `partial=true` | ≥1 output PARTIAL | + `warnings` = limitation codes |
| `failed` | no usable output | `error{code, message, retryable}`, `artifact_refs` may hold an INVALID artifact |
| `rejected` | contract/scope violation before work | `error.code` ∈ {`SPEC_ISSUE`, `NO_ACCESS`} |
| `input_required` | ambiguous entity (e.g. several units match a code) | `question{text, options, input_id}` |
| `canceled` | task cancelled | — |

Idempotency: same `idempotency_key` + same `input_refs` ⇒ the agent returns the previously stored refs
(Insight already implements this, [agent.py:139](../../agents/insight/vdagent_insight/agent.py#L139)).

## 3. Operations per agent

### 3.1 Data (producer of `dataset`, `metric`, `dq`)

**IMPLEMENTED in WS2** ([steps.py](../../agents/data/vdagent_data/steps.py), verified by `agents/data/vdagent_data/tests/test_steps.py`):

| Operation | `spec` (extra keys rejected) | Output artifacts | Errors (`AgentReport.error.code` → ErrorClass) |
|---|---|---|---|
| `fetch_units` | `{subject_unit_code: str, population: "subject" \| "peer_candidates" = "subject", project_ids?: [str]}` | `dataset(re_dataset@1)`, `metric(re_metric@1)`, `dq(re_dq@1)` | `UNIT_NOT_FOUND`→NO_DATA, `UNIT_AMBIGUOUS`→`input_required`, `SUBJECT_AREA_UNAVAILABLE`→DATA_QUALITY |
| `aggregate_metrics` | `{metrics: [str]≥1, group_by?: [project_key\|zone_key\|unit_type\|floor_band\|launch_batch_id\|inventory_status], filters?: {same keys: str}}` | same three (dataset table `unit_inventory`; metric rows `statistic: "median"`, `n`) | `UNKNOWN_METRIC`, `EMPTY_POPULATION`→NO_DATA |
| both | — | — | `UNKNOWN_OPERATION`, `INVALID_SPEC`, `INVALID_STEPSPEC`, `UNSUPPORTED_CONTRACT`, `SNAPSHOT_REQUIRED`, `SNAPSHOT_UNKNOWN`, `SNAPSHOT_NOT_APPROVED`, `SEMANTIC_VERSION_REQUIRED`, `SEMANTIC_VERSION_MISMATCH` → SPEC_ISSUE (`rejected`); `USER_CONTEXT_MISMATCH`→NO_ACCESS; `RESULT_TRUNCATED`→DATA_QUALITY; `TOOL_FAILED`→TRANSIENT (retryable); `INTERNAL_ERROR`→FATAL |

Reply: `render_agent_report` text (Vietnamese summary + one ```json fence holding `AgentReport@1`), no tool calls.
Population `peer_candidates` = every unit of the subject's `unit_type` inside the caller's scope (no batch, status or
area filter); candidates without a usable `net_area_m2` are excluded with `PEER_AREA_UNAVAILABLE:n`. Peer
selection is not done by Data (WS3; see B-11). `aggregate_metrics` supports medians of `dom_days`,
`net_price_per_m2_vnd`, `asking_price_vnd`, `net_area_m2`; other known metrics return null rows + `METRIC_UNAVAILABLE`.
The free-text LLM path is unchanged ([prompts/system.md:27](../../agents/data/vdagent_data/prompts/system.md#L27): retail tools).

### 3.2 Insight (producer of `insight`)

**IMPLEMENTED in WS3** ([stepspec.py](../../agents/insight/vdagent_insight/stepspec.py)): operation `explain_unit`, spec
`{intent, tasks[≥1], analysis_scope}` (extra keys rejected); `input_refs` = exactly one pinned `dataset`, `metric`, `dq`
(resolver: [step_inputs.py](../../contracts/vdagent_contracts/step_inputs.py)). Output: one `insight` artifact,
`schema_version` `insight.v2`, `input_artifact_refs` = the three Data refs, `evidence_refs` = the Data artifacts cited,
`limitations` = Data limitations ∪ Insight limitation codes ∪ `FIELD_UNAVAILABLE:asking_price_per_m2`, payload
`{insight, input_view, local_artifact, request}`. Error codes: resolver codes (below) + `UNKNOWN_OPERATION`,
`INVALID_SPEC`, `SEMANTIC_CONFIG_UNKNOWN`, `SCOPE_VIOLATION`, pipeline `E02`/`E03`/`E04`, `TOOL_FAILED`.
The sketch below is the original design.


| Operation | `spec` | Inputs (`input_refs`) | Output | Errors |
|---|---|---|---|---|
| `explain_unit` | `{intent: SLOW_MOVING_INVESTIGATION|PEER_GROUP_COMPARISON|PERFORMANCE_METRIC_LOOKUP, tasks: [T1..T7], analysis_scope}` | HARD: `dataset`, `metric`, `dq`; SOFT: `market_context`, `comparison` | `insight` envelope (`insight.v2` payload) | E02→`WRONG_RESULT`, E03→`SPEC_ISSUE`, E04→`NO_ACCESS`, E16 deadline→PARTIAL, E18 memory→warning |

Adapter (WS3): StepSpec → `InsightTaskRequest` ([contracts.py:121-137](../../agents/insight/vdagent_insight/contracts.py#L121)):
`run_id/task_id` = uuid5 of Backend ids (bridge already does this, [bridge.py:324-329](../../agents/insight/vdagent_insight/bridge.py#L324));
`input_artifact_refs` = StepSpec `input_refs` resolved through a new MCP-backed `ArtifactReader` replacing
`ExportArtifactReader` in the integration path ([runtime.py:109-127](../../agents/insight/vdagent_insight/runtime.py#L109)).
Output envelope mapping from Insight's private envelope ([contracts.py:315-329](../../agents/insight/vdagent_insight/contracts.py#L315)):

| Insight field | Shared envelope field | Transform |
|---|---|---|
| `limitations: list[Limitation]` | `limitations: list[str]` | `f"{code}:{detail}"`; full objects stay in `payload.limitations_detail` |
| `evidence_refs: list[str]` | `evidence_refs: list[ArtifactRef]` | parse `<artifact_id>` + look up version/type |
| `producer` | `producer` | same shape |
| `content_hash` | store-assigned | Insight keeps its own hash in payload for replay |

### 3.3 Compare (producer of `peer_definition`, `comparison`)

**IMPLEMENTED in WS3** ([stepspec.py](../../agents/compare/vdagent_compare/stepspec.py)): operation `compare_to_peers`,
spec `{subject{entityType:"unit", entityCode|entityId}, comparisonMode=peer_group|head_to_head|cohort|ranking,
metricsRequested?}`; same three pinned inputs (HARD: all three — the original sketch had metric SOFT). Outputs:
`peer_definition@1` then `comparison@1` (pins the peer definition as 4th input); payload = engine body with floats
as decimal strings + `areaTolerance{ratio, percent, source}`, `minPeerCount{value 5, source: engine default (B-2)}`,
`engineArtifactId`, `engineContentHash`, `engineLimitations`; `comparison.subject{entityId: DW key}`. Engine
`reason_code`s: `SUBJECT_NOT_FOUND`→NO_DATA, `PERMISSION_DENIED`→NO_ACCESS, `SUBJECT_AMBIGUOUS`/`CLARIFICATION_NEEDED`→
NEED_INPUT, `INVALID_INPUT`→SPEC_ISSUE. Status is PARTIAL while B-2 is open. The sketch below is the original design.

Resolver error codes (shared by Insight and Compare): `SNAPSHOT_REQUIRED`, `SEMANTIC_VERSION_REQUIRED`, `MISSING_INPUT`,
`INPUT_HASH_REQUIRED`, `INPUT_SCHEMA_UNSUPPORTED`, `SNAPSHOT_MISMATCH`, `SEMANTIC_VERSION_MISMATCH` → SPEC_ISSUE;
`INPUT_NOT_FOUND` → NO_DATA; `INPUT_TYPE_MISMATCH`, `INPUT_HASH_MISMATCH`, `LINEAGE_MISMATCH` → WRONG_RESULT;
`INPUT_INVALID` → DATA_QUALITY; `USER_CONTEXT_MISMATCH`, `SCOPE_VIOLATION` → NO_ACCESS.


| Operation | `spec` | Inputs | Output | Errors |
|---|---|---|---|---|
| `compare_to_peers` | `{subject{entityType:"unit", entityCode|entityId}, comparisonMode: peer_group|head_to_head|cohort|ranking, metricsRequested[], areaBandFraction?}` | HARD: `dataset(population=peer_candidates)`, `dq`; SOFT: `metric` | `peer_definition`, `comparison` (`comparison@1`) | `INVALID_INPUT`→`SPEC_ISSUE`, `NO_PEERS`→`NO_DATA`, `SUBJECT_AREA_UNAVAILABLE`→`DATA_QUALITY`, ambiguity→`input_required` |

Adapter (WS3): build `DataPackage` from the dataset artifact instead of CSV ([vh_data.py:107-148](../../agents/compare/vdagent_compare/vh_data.py#L107));
`Unit.area_m2 ← net_area_m2` (D9); tolerance fraction → percent conversion (DQ-4); `min_group_size` (DQ-5);
metrics per CANONICAL §5.6 (nulls + limitations, never 0). Output fixes: `producer` object (today a string,
[vh_service.py:165](../../agents/compare/vdagent_compare/vh_service.py#L165)), numbers as decimal strings (today float, [vh_math.py:49](../../agents/compare/vdagent_compare/vh_math.py#L49)).
Existing `chartHints[]` ([vh_service.py:385-401](../../agents/compare/vdagent_compare/vh_service.py#L385)) become the Chart input for comparison visuals.

### 3.4 Chart (producer of `chart_spec`)

**IMPLEMENTED in WS4** ([stepspec.py](../../agents/chart/vdagent_chart/stepspec.py)): operation `draw_chart`, spec
`{chart_type?}` (must be in the policy's `allowed_chart_types`, else `UNSUPPORTED_CHART_TYPE`); `input_refs` = pinned
`insight` and/or `comparison` (+ optional `peer_definition`), resolved by `resolve_analysis_inputs` (extra types →
`INPUT_TYPE_UNSUPPORTED`; different datasets or a comparison not pinning the given peer definition →
`LINEAGE_MISMATCH`). Output: one `chart_spec@1` per chart, `input_artifact_refs` = [dataset, upstream shown],
payload `{chart_id, target_id, visual_question, chart_type, title, vega_lite, plotly, semantic_spec, dataset,
bindings[{record_index, field, value_exact, unit, source_ref, metric_id, finding_ids?, evidence_refs?}], selection,
validation, policy_ref, lineage{insight, comparison, metric_ids, finding_ids}}`.
**Insight input (2026-10-01):** Chart reads only the insight's typed `payload.evidence` (`insight_evidence@2`,
[data-contract §10](data-contract.md)) — never `claim.rendered_text`, `display` or
`numeric_bindings`. Every Insight KPI value and every Compare subject/peer value is checked against the pinned Data
dataset before it is drawn; no LLM on this path (question, type and titles come from the typed intent and the metric
catalog). Limitations: upstream ∪ `UPSTREAM_MISSING:<type>`, `NOT_CHARTED_NULL:<metric>`,
`INSIGHT_EVIDENCE_MISSING|INVALID:<reason>`, `EVIDENCE_UNRESOLVED|EVIDENCE_VALUE_MISMATCH:<finding>/<metric>`,
`VALUE_MISMATCH_WITH_DATASET:comparison:<metric>`, `CONFLICTING_VALUES:insight:<metric>`,
`VISUAL_NEEDS_COMPARISON:<finding>:<metric>`,
`CHART_TARGET_FAILED:<target>:<code>`. Errors: resolver codes + `UNKNOWN_OPERATION`, `INVALID_SPEC`,
`UNSUPPORTED_CHART_TYPE`, `NOTHING_TO_CHART` (message lists every reason), `CHART_FAILED`, `TOOL_FAILED`. Logs: one
`CHART_SPEC_STORED` / `CHART_TARGET_REJECTED` / `CHART_FINDING_SKIPPED` line per chart or finding and one
`CHART_STEP_DONE` per step (`vdagent.plugin.vdagent_chart`, lineage only). The sketch below is the original design.


| Operation | `spec` | Inputs | Output | Errors |
|---|---|---|---|---|
| `draw_chart` | `{visual_targets[{target_id, visual_question, preferred_chart_type?, source_ref}]}` | HARD: ≥1 of `comparison`, `insight`; SOFT: the other, `metric` | `chart_spec` (`chart_spec@1`) per target | missing/hash-mismatch ref → `failed`, `NO_DATA`/`WRONG_RESULT`; unsupported chart → `SPEC_ISSUE` |

Mapping to the existing `ChartTaskInput` ([chart contracts.py:46-60](../../agents/chart/vdagent_chart/contracts.py#L46)):
`artifact_refs[ArtifactRef(artifact_id, version, expected_hash = envelope.content_hash)]`; `Scope.snapshot_id = snapshot_id`;
`ArtifactType` literal gains `comparison`/`insight` already present; `metric` read from the store.
`chart_spec@1` payload: `{chart_id, chart_type, vega_lite, dataset_hash, bindings[{field, source_ref}], validation{overall_result}, presentation{title, subtitle}}`.
Every plotted value must equal the value at its `source_ref` (C-CHT-01).
**Audit F-01:** `kpi_card` specs carry `mark.type: "kpi_card"`, which is not Vega-Lite; they fail in the browser.
Report's `validate_chart` only checks the `$schema` prefix, so such specs pass evidence validation.
`chart demo` / `chart ask` (synthetic, [agent.py:30-54](../../agents/chart/vdagent_chart/agent.py#L30), [mock_upstream.py:158,171](../../agents/chart/vdagent_chart/mock_upstream.py#L158)) only behind an explicit demo flag (D6).
Persistence: via MCP `artifact_put`, not `ctx.artifacts` (absent from the SDK, [agent.py:76](../../agents/chart/vdagent_chart/agent.py#L76)).

### 3.5 Report (producer of `report`)

| Operation | `spec` | Inputs | Output | Errors |
|---|---|---|---|---|
| `draft_report` | `{title, sections[]?, language:"vi"}` | HARD: ≥1 analytical artifact; SOFT: `chart_spec`, `insight`, `comparison` | `report` envelope (`report@1`: `{markdown, citations[{claim_id, source_ref}]}`) + saved `rp_…` | Jev reject after revision → `completed, partial=true` + `REVIEW_REJECTED`; unresolved ref → `failed WRONG_RESULT` |

Needs `save_report` to accept `{{chart_spec:art_…@v}}` embeds (D7); today only `{{chart:ch_…}}` / `{{dataset:ds_…}}`
([mcp/handlers.py `_create_chart`](../../backend/vdagent_backend/mcp/handlers.py)). `create_chart` stays for the retail domain.

### 3.6 Orchestrator (producer of `run_state`, `run_summary`)


**Capability policy (2026-10-01, [planner.py](../../agents/orchestrator/vdagent_orchestrator/planner.py) `capability_policy`).**
From the requested outputs (`wants`, after `normalize_wants`) each agent is `required`, `optional` or `forbidden`:
`data` is required; `insight` / `compare` / `chart` / `report` are required when explain / compare / chart / report is
requested (chart or report without a named analysis require both analyses; report requires chart); when a chart is
requested the analysis not asked for is `optional` (Chart can draw it); everything else is `forbidden`. An LLM plan is
accepted when required ⊆ proposed ⊆ required ∪ optional and its dependencies are valid (`LLM_PLAN_MISSING_STEP`,
`LLM_PLAN_UNEXPECTED_STEP`, `LLM_PLAN_INVALID_DEPENDENCY` otherwise); the DAG that runs is always compiled by code from
the required set (`build_plan`), optional proposals are recorded in `provenance.normalized.dropped_optional`.

**IMPLEMENTED in WS5.** Inbound: `AnalysisRequest@1` `{contract, question, subject_unit_code, wants ⊆ [explain,
compare, chart], snapshot_id, semantic_config_version}` (all required; no default snapshot), or free text classified
deterministically when `ORCH_LLM=off` (snapshot from `ORCH_SNAPSHOT_ID`). Outbound per step: `StepSpec@1` with
`run_id` = engine task id, `plan_id`, `idempotency_key` = `plan_id:step_id`, `user_context` from `get_user_context`,
`deadline_s` from the catalog, `input_refs` = the checked output refs of the dependencies. Reply accepted only as one
`AgentReport@1` for that step. Output: `run_state@1` (plan, waves, per-step status/timestamps/refs/error/limitations)
and the chat answer; no `run_summary` yet. The sketch below is the original design.


Plan = ordered `StepSpec`s with dependencies derived from each operation's `requires`/`uses_if_present`.
Golden plan: `B1 data.fetch_units` → (`B2 insight.explain_unit` ∥ `B3 compare.compare_to_peers`) → `B4 chart.draw_chart`
→ `B5 report.draft_report` (only if `OutputKind.REPORT`). `run_state` payload: `{plan_id, steps[{step_id, agent, operation, state, artifact_refs, error?}], output_kinds}`.

## 4. Edge matrix (target)

| Edge | Message | Artifacts passed | Consumer check | Current state |
|---|---|---|---|---|
| User → Orchestrator | `AnalysisRequest@1` or free text | — | deterministic planner (+ scope from `get_user_context`) | IMPLEMENTED (WS5); LLM planning not yet |
| Orchestrator → Data | `StepSpec fetch_units` | — | APPROVED snapshot | IMPLEMENTED + VERIFIED (WS5) |
| Data → Orchestrator | `AgentReport` | dataset, metric, dq | refs exist | IMPLEMENTED (WS2) |
| Orchestrator → Insight | `StepSpec explain_unit` | dataset, metric, dq | resolver + E02/E03/E04 | IMPLEMENTED + VERIFIED (WS5), parallel with Compare |
| Orchestrator → Compare | `StepSpec compare_to_peers` | dataset, metric, dq | resolver + D9 | IMPLEMENTED + VERIFIED (WS5), parallel with Insight |
| Insight/Compare → Orchestrator | `AgentReport` | insight / peer_definition, comparison | refs resolvable | IMPLEMENTED (WS3) |
| Orchestrator → Chart | `StepSpec draw_chart` | insight, comparison, peer_definition | resolver (hash, snapshot, one dataset) | IMPLEMENTED + VERIFIED (WS5) |
| Orchestrator → Report | `StepSpec draft_report` | chart_spec, insight, comparison | all refs resolvable | MISMATCH (charts itself from `ds_`) |
| Orchestrator → User | text with `art_…`/`rp_…` citations | run_summary | — | PARTIAL |

## 5. Error-class mapping

| Agent code | ErrorClass | Orchestrator action |
|---|---|---|
| Data unit not found / empty scope | `NO_DATA` | stop dependent steps; answer with limitation |
| Scope violation (E04, `re_run_query` hidden rows only) | `NO_ACCESS` | stop; never retry |
| Snapshot DRAFT / mismatch (E03) | `SPEC_ISSUE` | re-plan with pinned snapshot once |
| Hash mismatch, invalid ref (E02) | `WRONG_RESULT` | retry once after refetch |
| LLM timeout / unavailable | `TRANSIENT` | Insight/Compare fall back to TEMPLATE/rules; otherwise one retry |
| `DEADLINE_EXCEEDED` (engine) | `TRANSIENT` | mark step failed, continue SOFT dependents with `UPSTREAM_FAILED` |
| Ambiguous entity | `NEED_INPUT` | ask the user |
| Anything else | `FATAL` | fail run |

## 6. Examples

Valid request (Orchestrator → Compare):
```json
{"contract":"StepSpec@1","run_id":"tsk_01","plan_id":"pl_01","step_id":"B3","idempotency_key":"pl_01:B3",
 "operation":"compare_to_peers",
 "spec":{"subject":{"entityType":"unit","entityCode":"A12-08"},"comparisonMode":"peer_group",
         "metricsRequested":["net_asking_price_per_m2","dom"]},
 "user_context":{"user_id":"u_000000000001","role":"SALES_OPS","authorized_scope":{"project_ids":["PRJ-X"],"zone_ids":[]}},
 "snapshot_id":"SNAP-2026-09-28","semantic_config_version":"sc-1",
 "input_refs":[{"artifact_id":"art_ds01","version":1,"artifact_type":"dataset"},
               {"artifact_id":"art_dq01","version":1,"artifact_type":"dq"}],
 "deadline_s":30,"original_question":"Vì sao căn A12-08 bán chậm?"}
```

Valid reply:
```json
{"contract":"AgentReport@1","run_id":"tsk_01","step_id":"B3","idempotency_key":"pl_01:B3","state":"completed",
 "partial":true,"snapshot_id":"SNAP-2026-09-28","semantic_config_version":"sc-1",
 "artifact_refs":[{"artifact_id":"art_pd01","version":1,"artifact_type":"peer_definition"},
                  {"artifact_id":"art_cmp01","version":1,"artifact_type":"comparison"}],
 "warnings":["METRIC_UNAVAILABLE:discount_pct","METRIC_UNAVAILABLE:inquiry_leads_30d"],
 "summary":"7 căn tương đồng; giá ròng/m² cao hơn trung vị 12,40%."}
```

Invalid requests:

| Fragment | Rejection |
|---|---|
| `"step_id":"3"` | pattern `^B[1-9][0-9]*$` (existing) |
| `"idempotency_key":"x"` | must equal `plan_id:step_id` (existing) |
| `"snapshot_id":"SNAP-2026-09-29"` | DRAFT → `rejected SPEC_ISSUE` |
| `input_refs` with a dataset of `SNAP-2026-08-31` | snapshot mismatch → `rejected SPEC_ISSUE` |
| `user_context.authorized_scope.project_ids` = `["PRJ-Y"]` for A12-08 | `rejected NO_ACCESS` |

## 7. WS6 implemented contract update (2026-09-30)

| Edge / operation | Actual contract and validation | Verified outcome |
|---|---|---|
| Orchestrator → Report (B5) | `StepSpec@1 draft_report`; dependencies B2/B3/B4; `any` dependency mode forwards only verified completed refs; failed upstream becomes `UPSTREAM_FAILED:<agent>` limitation | B5 receives exactly Insight + PeerDefinition + Comparison + chart-spec refs; repeats reuse completed B5 |
| Report inputs | `resolve_analysis_inputs(..., chart_specs=True)` validates caller ownership, pinned hash, type/schema, usable status, snapshot, semantic, one dataset, and Compare→PeerDefinition lineage | invalid hash/ref/snapshot/semantic/dataset/user combinations reject or fail correctly |
| Report output | `AgentReport@1` completed with one pinned `report@1`; payload has six sections, statements/source refs, charts/tables/actions, validation and `delivery.report_id` | 28 statements and all chart bindings verified in golden flow |
| Report delivery | `save_report` validates pinned shared `chart_spec` embeds; REST exposes `GET /api/chart-specs/{id}/{version}` owner-scoped; frontend `ChartSpecView` renders Vega-Lite | saved `rp_…` equals report markdown; raw embed tokens are not used as frontend output |

Error additions: `UNKNOWN_OPERATION`, `INVALID_SPEC`, input-resolver codes, `EVIDENCE_INVALID` (`WRONG_RESULT`), `REPORT_SAVE_FAILED` (`TRANSIENT`), and `TOOL_FAILED` (`TRANSIENT`). Chat/free-text legacy Report behavior is retained; keyless structured mode is `REPORT_LLM=off`.

> WS7 F-01 resolved: `chart_spec.payload.vega_lite` must pass `vdagent_contracts.vega_lite.validate_vega_lite` (Vega-Lite v6). `kpi_card` renders as a `text` mark. Chart refuses invalid specs, and Report returns `EVIDENCE_INVALID` for them.

> Orchestrator LLM planner output (`orch-llm-plan-1.0.0`):

- Shape: `{intent: {in_scope, subject_unit_code, wants}, steps: [{step_id, agent, operation, depends_on}]}`, with no other fields allowed.
- Specs, pins and bindings are always filled in by code.
- Rejection codes: `LLM_PLAN_MALFORMED`, `UNSUPPORTED_AGENT`, `UNSUPPORTED_OPERATION`, `UNKNOWN_DEPENDENCY`, `CYCLE`, `LLM_PLAN_INVALID_DEPENDENCY`, `LLM_PLAN_MISSING_STEP`, `LLM_PLAN_UNGROUNDED`, `LLM_PLAN_UNAVAILABLE`.
