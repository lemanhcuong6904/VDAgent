# Canonical Data Contract — real-estate flow

Status: decisions D1–D10 **APPROVED** (2026-09-30). Implementation: envelope/store rules of §3 and `peer_rules` are
IMPLEMENTED (WS1); `re_dataset@1`/`re_metric@1`/`re_dq@1` payloads are IMPLEMENTED by the Data agent (WS2, §4); consumer-side field
mapping of §5 is IMPLEMENTED for Insight and Compare (WS3; see the note at the top of §5);
D2b segment mapping, `net_area_m2` business meaning and `min_group_size` are BLOCKED. `PROPOSED_NEW` below is an
evidence class (a field/rule introduced by this design), not an approval status. Branch `agent_a/debug` @ `4b420e9`.
Companion docs: [INTEGRATION_MASTER_PLAN.md](INTEGRATION_MASTER_PLAN.md), [AGENT_CONTRACT_MATRIX.md](AGENT_CONTRACT_MATRIX.md), [E2E_TEST_PLAN.md](E2E_TEST_PLAN.md).

Evidence labels used in this document:

| Label | Meaning |
|---|---|
| VERIFIED_EXISTING | Field exists in the DW schema/seed and was read back during the audit |
| DERIVED | Computed from VERIFIED_EXISTING fields by a stated formula |
| PROPOSED_NEW | New field/rule introduced by this design |
| UNAVAILABLE | No source in the DW; must be emitted as `null` + limitation, never defaulted |
| UNRESOLVED | Source exists but semantics/type conflict needs a decision |

All DW facts below were checked against `backend/vdagent_backend/re_warehouse/` and a scratch build of it
(`build()` into the session scratchpad, checksum prefix `523af4c6a963a2ed`); the repository `var/` was not touched.

---

## 1. Source of truth (D1, APPROVED)

Canonical source = the Backend real-estate DW mock `re_warehouse` read by the Data agent through MCP
`re_run_query` (scoped by `authorized_scope`, [re_sql.py:1-7](../../backend/vdagent_backend/mcp/re_sql.py#L1-L7)).

| Property | Value | Evidence |
|---|---|---|
| Schema | DW v3.1.0 mock, 14 tables | [schema.sql](../../backend/vdagent_backend/re_warehouse/schema.sql) |
| Snapshots | `SNAP-2026-08-31` APPROVED, `SNAP-2026-09-28` APPROVED, `SNAP-2026-09-29` **DRAFT** | [re_warehouse/__init__.py:41-46](../../backend/vdagent_backend/re_warehouse/__init__.py#L41-L46) |
| Latest approved | `SNAP-2026-09-28` (`snapshot_date_key` 20260928) | same, L46 |
| Semantic config version | `sc-1` | [semantic_config.py:11](../../backend/vdagent_backend/re_warehouse/semantic_config.py#L11) |
| Keys | TEXT: `unit_key` `U-PRJ-X-A12-08`, `project_key` `PRJ-X`, `zone_key` `ZN-A`, `channel_key` `CH-01` | schema.sql:24-66 |
| Numbers | VND as INTEGER; areas, percentages, ratios as decimal strings (TEXT); no REAL columns | schema.sql:1-3 |

Non-canonical sources (kept for isolated regression tests, D10 APPROVED): Insight export pack
(`agents/insight/vdagent_insight/tests/fixtures/export_sample`, `SNAP-20260630-01`, semantic `3.1.0`, INT keys),
Compare hero fixture (`fixtures/hero_a12_08.json`, semantic `1.0.0`), Chart demo (`demo/artifacts.json`, A12-08 DOM 126, placeholder hashes).

**Snapshot rule (APPROVED; enforcement PLANNED in WS2):** every query and artifact of one run pins exactly one `snapshot_id` whose
`snapshot_manifest.status = 'APPROVED'`. Evidence it matters: A12-08 DOM is 110 / **138** / 139 at
20260831 / 20260928 / 20260929 (the last is DRAFT). An unfiltered "latest row" read returns 139.

---

## 2. `net_area_m2` — canonical area (D9, RESOLVED)

Decision: `dim_unit_master.net_area_m2` is the only area used for peer-group selection and area similarity.
`area_m2` is never substituted when `net_area_m2` is null, empty or unparsable.

### 2.1 Data-quality findings (verified)

| Check | Result | Evidence |
|---|---|---|
| Declared type / nullability | `TEXT NOT NULL`, decimal string, comment `TODO(spec-gap): net vs gross` | [schema.sql:44](../../backend/vdagent_backend/re_warehouse/schema.sql#L44) |
| Unit of measure | m² (implied by name; not documented further) | schema.sql:43-44 |
| Population coverage | 179/179 units, 0 null, 0 empty | scratch DW query |
| **Provenance** | **Synthetic**: `net_area_m2 = round(area_m2 × 0.92, 2)` for every unit (0 exceptions) | [fixtures.py:126](../../backend/vdagent_backend/re_warehouse/fixtures.py#L126), [__init__.py:128](../../backend/vdagent_backend/re_warehouse/__init__.py#L128) |
| A12-08 value | `net_area_m2 = 63.02` (gross `area_m2 = 68.50`) | scratch DW |
| Peer band (±10 %) membership for A12-08 | identical under net and gross for all 12 candidates | scratch DW (table §2.2) |
| Similarity scores | 4 of 7 golden scores change in the 4th decimal (rank order unchanged) | §2.2 |
| Existing tests using gross | `backend/tests/test_re_fixtures.py:63-81` compute the area term with `area_m2` | file |
| Compare CSV reader | already maps `area_m2 ← net_area_m2` | [vh_data.py:138](../../agents/compare/vdagent_compare/vh_data.py#L138) |
| Compare hero reader | maps `area_m2 ← area_m2` (68.5 = gross) — **violates D9** | [vh_data.py:162](../../agents/compare/vdagent_compare/vh_data.py#L162) |
| Compare peer rule field name | `Unit.area_m2` used for band and score | [vh_peers.py:78,88-90](../../agents/compare/vdagent_compare/vh_peers.py#L78) |
| Insight models | carry no area field at all | [contracts.py:481-495](../../agents/insight/vdagent_insight/contracts.py#L481) |
| Export pack basis | manifest `area_basis = NET_INTERNAL_M2` | `export_sample/snapshot_manifest.csv` |

### 2.2 A12-08 similarity under D9 (formula of test_re_fixtures.py:63-77, area term swapped)

| Peer | net_area_m2 | score (gross, current test) | score (net, D9) |
|---|---|---|---|
| A12-11 | 64.58 | 0.9255 | **0.9257** |
| A10-02 | 60.72 | 0.8905 | 0.8905 |
| A14-03 | 63.48 | 0.8781 | 0.8781 |
| A06-01 | 61.73 | 0.8554 | **0.8553** |
| B09-05 | 59.43 | 0.7292 | **0.7291** |
| B11-07 | 66.42 | 0.5880 | **0.5881** |
| B15-02 | 68.08 | 0.5758 | 0.5758 |

Discrepancies to resolve (not changed by this design):
- **DQ-1** `net_area_m2` is a fixed-ratio synthetic value; the DW spec gap (net vs gross) is still open upstream. Real DW semantics UNVERIFIED.
- **DQ-2** `test_re_fixtures.py:79-81` asserts gross-based scores; under D9 the golden values become the "net" column above. Owner must update that test in WS1/WS3 (TDD: change expectation first).
- **DQ-3** Compare hero fixture area is gross; retire it from integration paths (D10) or re-base to net.
- **DQ-4** Tolerance unit mismatch: `sc-1` stores `peer_area_tolerance_pct = "0.10"` (a fraction, [semantic_config.py:74](../../backend/vdagent_backend/re_warehouse/semantic_config.py#L74)); Compare reads the key as **percent** and rejects values outside 5–10 (`INVALID_INPUT`, [vh_peers.py:124-125](../../agents/compare/vdagent_compare/vh_peers.py#L124-L125), read at [vh_service.py:264](../../agents/compare/vdagent_compare/vh_service.py#L264)). Canonical rule: tolerance is a **fraction** in `[0.05, 0.10]`; the Compare adapter converts.
- **DQ-5** `sc-1` has `min_group_size = 5` with status **PENDING** ([semantic_config.py:85](../../backend/vdagent_backend/re_warehouse/semantic_config.py#L85)); Compare looks for `min_peer_count` and silently defaults to 5 ([vh_service.py:265](../../agents/compare/vdagent_compare/vh_service.py#L265)). Canonical: read `min_group_size`; if not APPROVED, add limitation `CONFIG_PENDING:min_group_size`.

### 2.3 Null / invalid handling rule

| Situation | Behaviour |
|---|---|
| Subject `net_area_m2` null/unparsable | Compare returns `INVALID` comparison, `reason_code = SUBJECT_AREA_UNAVAILABLE`, ErrorClass `DATA_QUALITY`; no fallback to `area_m2` |
| Candidate `net_area_m2` null/unparsable | Candidate excluded with reason `net_area_unavailable`, counted in `excludedSummary`; limitation `PEER_AREA_UNAVAILABLE:<n>` |
| All candidates excluded | `INVALID`, `reason_code = NO_PEERS`, ErrorClass `NO_DATA` |

---

## 3. Shared envelope (reuse, proposed rules)

Reuse `vdagent_contracts.envelope.ArtifactEnvelope` / `ArtifactDraft` unchanged in shape
([envelope.py:62-131](../../contracts/vdagent_contracts/envelope.py#L62-L131)); store in `backend.db` via
`artifact_store.put/get` ([artifact_store.py:53,134](../../backend/vdagent_backend/db/artifact_store.py#L53)) through MCP
`artifact_put/get/list` ([tools.py:171-200](../../backend/vdagent_backend/mcp/tools.py#L171-L200)).

| Field | Type | Req | Rule (PROPOSED_NEW where marked) |
|---|---|---|---|
| `artifact_id` | str `art_…` | store-assigned | Existing |
| `version` | int ≥1 | store-assigned | New version supersedes old (existing) |
| `run_id` | str | yes | = orchestrator `task_id` (existing default, tools.py:487) |
| `artifact_type` | enum `ArtifactType` | yes | Writer restricted by `WRITABLE_TYPES` (tools.py:52-60) |
| `schema_version` | str | yes | Per payload: `re_dataset@1`, `re_metric@1`, `re_dq@1`, `insight.v2`, `comparison@1`, `chart_spec@1`, `report@1` (PROPOSED_NEW values) |
| `status` | `DRAFT/VALID/PARTIAL/INVALID` | yes | PARTIAL needs `limitations` (existing validator) |
| `producer` | `Producer{agent, agent_version, prompt_version?, model_id?}` | yes | Object, not string (Compare today writes a string, vh_service.py:165) |
| `content_hash` | sha256 hex | store-assigned | Existing |
| `snapshot_refs` | list[str] | yes | **Exactly one**, APPROVED (PROPOSED_NEW) |
| `semantic_config_version` | str | yes for data/analytic/chart/report | = `sc-1` for the golden (PROPOSED_NEW requiredness) |
| `source_refs` | list[str] | yes for `dataset/metric/dq` | `re:<table>` or `re:<table>#sql:<sha256>` |
| `input_artifact_refs` | list[`ArtifactRef`] | yes except `data_package/dataset` | Store checks each exists for this user (PROPOSED_NEW) |
| `evidence_refs` | list[`ArtifactRef`] | optional | |
| `limitations` | list[str] | PARTIAL ⇒ ≥1 | Codes `CODE[:detail]` (§7); rich objects go into the payload |
| `reason_code`, `reason` | str | INVALID ⇒ required | PROPOSED_NEW requiredness |
| `payload` | object | yes | No floats (store rejects floats; MCP parses JSON floats as Decimal, tools.py:480) |

**Audit F-02:** `compute_content_hash` includes `status`; the store later sets `status = SUPERSEDED`, so a superseded
version no longer matches its stored hash on recomputation (pinned refs still compare against the stored hash).

Cross-run consistency: all `input_artifact_refs` of an artifact must share its `snapshot_refs[0]`
and `semantic_config_version`; otherwise the consumer returns `SPEC_ISSUE` and writes nothing.

**WS1 implementation status (2026-09-30):**

| Rule | State |
|---|---|
| `ArtifactRef.content_hash` optional expected hash (`^[0-9a-f]{64}$`) | IMPLEMENTED ([envelope.py:61](../../contracts/vdagent_contracts/envelope.py#L61)) |
| `ArtifactDraft.snapshot_refs` ≤ 1 | IMPLEMENTED (draft only; "exactly one" needs D1 because legacy artifacts carry none) |
| Input refs exist for the user at that version, same type, hash equal when pinned | IMPLEMENTED in the store ([artifact_store.py:53](../../backend/vdagent_backend/db/artifact_store.py#L53)) |
| Snapshot / semantic version agree across draft and inputs, compared wherever declared | IMPLEMENTED (legacy artifacts that declare none are not compared) |
| Snapshot is APPROVED | NOT IMPLEMENTED — WS2 (snapshot status lives in `re_warehouse.db`) |
| `semantic_config_version` required, `INVALID` ⇒ `reason_code`, `schema_version` values of this table | NOT IMPLEMENTED — blocked on D1/D2/D8 |
| Floats rejected | pre-existing, re-verified by tests |

JSON-path reference format: `<artifact_id>@<version>#<json_pointer>`, e.g. `art_m1@1#/metrics/0/value` —
IMPLEMENTED for every value a `chart_spec` displays (`payload.bindings[].source_ref`, WS4; resolver
`vdagent_chart.stepspec.resolve_pointer`). A `chart_spec` stores non-integer numbers as decimal strings (store rule: no
float); `bindings[].value_exact` keeps the upstream representation (e.g. `"12.40"`).

---

## 4. Data artifacts (producer: data)

**WS2 implementation (VERIFIED, `agents/data/vdagent_data/tests/test_steps.py`).** Differences from the sketch below:
- `dataset.payload` keys: `snapshot`, `population{rule, subject_unit_key, candidate_filter, area_field}`, `tables`
  (`dim_project_profile`, `dim_zone_master`, `dim_unit_master`, `fact_unit_inventory_snapshot`,
  `dm_unit_friction_diagnostics`, `unit_diagnostic_causes`; `aggregate_metrics` uses one joined table `unit_inventory`),
  `row_counts`, `hidden_rows`, `excluded[{unit_code, reason}]`, `semantic_config{key: {value, status[, ratio]}}`,
  `queries[{table, sql_sha256, row_count}]`. Rows keep DW names and types (TEXT keys, decimal strings, INTEGER VND).
  `funnel_30d` is not a table; funnel coverage is in `dq.payload.coverage.fact_sales_funnel_daily`.
- `metric` rows for `fetch_units`: `dom_days`, `net_price_per_m2_vnd`, `asking_price_vnd`, `net_area_m2` (`M2`,
  string), `inquiry_leads_30d`, `subsidy_duration_mo`, `discount_pct` (always null), `dw_peer_n`
  (`dm_unit_friction_diagnostics.peer_n`), each with `source_ref` (`null` when the DW has no source).
- `dq.fields`: `net_area_m2`, `inventory_row`, `net_price_per_m2`, `asking_price_vnd`, `unsold_days_dom` over the
  considered population; limitation `DQ_MISSING:<field>:<n>`.
- Extra limitation codes in use: `DQ_MISSING`, `BLOCKED:D2b_segment_mapping`, `CONFIG_PENDING:<key>`.

### 4.1 `dataset` — `re_dataset@1`

```json
{
  "snapshot": {"snapshot_id": "SNAP-2026-09-28", "snapshot_date": "2026-09-28", "snapshot_date_key": 20260928,
               "semantic_config_version": "sc-1"},
  "scope": {"level": "UNIT", "project_ids": ["PRJ-X"], "zone_ids": [], "unit_ids": ["U-PRJ-X-A12-08"]},
  "population": {"rule": "peer_candidates", "subject_unit_key": "U-PRJ-X-A12-08"},
  "tables": {
    "dim_project_profile": [], "dim_zone_master": [], "dim_unit_master": [], "dim_sales_channel": [],
    "fact_unit_inventory_snapshot": [], "dm_unit_friction_diagnostics": [], "unit_diagnostic_causes": [],
    "funnel_30d": [], "fact_market_macro_monthly": []
  },
  "row_counts": {"dim_unit_master": 12},
  "hidden_rows": {"dim_unit_master": 1},
  "queries": [{"table": "dim_unit_master", "sql_sha256": "…"}]
}
```

Rows keep **DW column names and types** (TEXT keys, decimal strings). `funnel_30d` is DERIVED (§5.6).

### 4.2 `metric` — `re_metric@1`

| Field | Type | Semantics |
|---|---|---|
| `metrics[].metric_id` | str | e.g. `net_price_per_m2_vnd`, `dom_days` |
| `metrics[].calculation_ref` | str | `calc_<id>@1` |
| `metrics[].subject` | `{type: UNIT|ZONE|PROJECT, id, label}` | `id` = DW key |
| `metrics[].value` | decimal string \| null | null ⇒ must list limitation |
| `metrics[].unit` | `DAY|PCT|VND|VND_PER_M2|RATIO|COUNT|SCORE|M2` | `M2` is PROPOSED_NEW (for `net_area_m2`) |
| `metrics[].n` | int? | sample size |
| `metrics[].source_ref` | str | `re:<table>.<column>` |

### 4.3 `dq` — `re_dq@1`

`overall_status` (`VALID|PARTIAL|INVALID`), `snapshot_date`, `data_as_of` (= `snapshot_manifest.loaded_at`),
`fields[{field, missing_count, total, missing_pct, status}]` computed over the dataset population. Required
fields for the golden: `net_area_m2`, `net_price_per_m2`, `asking_price_vnd`, `unsold_days_dom`, `leads`.

---

## 5. Field mapping matrix

**WS3 status.** Insight: [dw_reader.py](../../agents/insight/vdagent_insight/dw_reader.py) implements §5.1–§5.5 with
these resolutions — keys kept as DW TEXT (`DwKey = int | str`, legacy ints unchanged); `unit_id`/`project_id`/`zone_id`
= key; `view_primary_type` gains `INTERNAL_COURT`, `inventory_status` gains `LOCKED`; `segment` raw (D2b BLOCKED, only
compared for equality); `subsidy_duration_mo`, `physical_defect_penalty`, `thermal_view_penalty`,
`recommended_action`, `peer_count` nullable (D8); `channel_key` TEXT from DW; `base_commission_pct`/`spiff_bonus_vnd`
from `dim_sales_channel` (added to the Data dataset in WS3); `asking_price_per_m2` null (no DW column); diagnostics
only for rows with `primary_cause_code`; `UnitRow.net_area_m2` via `peer_area`. Compare: [stepspec.py](../../agents/compare/vdagent_compare/stepspec.py)
`build_package` implements §5.6 (`net_asking_price_per_m2` ← `net_price_per_m2`, `dom` ← `unsold_days_dom`,
`area_m2` ← `net_area_m2`, `inquiry_leads_30d`/`discount_pct` None, `subsidy_duration_mo` from the mart). Insight's
semantic config for `sc-1`: [semantic_insight.sc-1.yaml](../../agents/insight/config/semantic_insight.sc-1.yaml)
(provenance per value; B-12). Tables below keep the original classification.


Format: DW source → canonical → transformation → consumer → test (see E2E_TEST_PLAN.md ids).

### 5.1 Unit (Insight `UnitRow`, [contracts.py:481-495](../../agents/insight/vdagent_insight/contracts.py#L481))

| DW source | Canonical | Transform | Consumer field | Class | Test |
|---|---|---|---|---|---|
| `dim_unit_master.unit_key` TEXT | `unit_key` str | none | Insight `unit_key: int` | **UNRESOLVED** → change Insight to `str` (D2) | C-INS-01 |
| — | `unit_id` | `= unit_key` | Insight `unit_id` | DERIVED (DW has no separate id) | C-INS-01 |
| `unit_code` | `unit_code` | none | `unit_code` | VERIFIED_EXISTING | C-INS-01 |
| `project_key` TEXT | `project_key` str | none | `project_key: int` | UNRESOLVED (D2) | C-INS-01 |
| `zone_key` TEXT | `zone_key` str | none | `zone_key: int` | UNRESOLVED (D2) | C-INS-01 |
| `unit_type` | `unit_type` | none | Literal STUDIO…PENTHOUSE | VERIFIED_EXISTING (DW values 1PN/2PN/3PN fit) | C-INS-01 |
| `floor_no` INTEGER | `floor_number` | rename | `floor_number` | VERIFIED_EXISTING | C-INS-01 |
| `floor_band` | `floor_band` | none | same Literal | VERIFIED_EXISTING | — |
| `balcony_orientation` | same | none | same Literal | VERIFIED_EXISTING | — |
| `view_primary_type` | same | none | Literal lacks `INTERNAL_COURT` (DW has RIVER, CITY_OPEN, INTERNAL_COURT, PARK) | **UNRESOLVED** → extend enum (D2) | C-INS-02 |
| `net_area_m2` | `net_area_m2` decimal str | none | Compare `Unit.area_m2` | VERIFIED_EXISTING (synthetic, DQ-1) | C-CMP-02 |
| `area_m2` | `gross_area_m2` | rename | none (informational) | VERIFIED_EXISTING | — |
| `launch_batch_id` | same | none | Compare, Insight `InventoryRow` | VERIFIED_EXISTING | — |
| `release_date` | same | none | — | VERIFIED_EXISTING | — |

### 5.2 Inventory (Insight `InventoryRow`, [contracts.py:497-512](../../agents/insight/vdagent_insight/contracts.py#L497))

| DW source | Canonical | Transform | Insight field / type | Class |
|---|---|---|---|---|
| `fact_unit_inventory_snapshot.snapshot_date_key` | same | filter = pinned snapshot | `snapshot_date_key: int` | VERIFIED_EXISTING |
| `.unit_key`, `.project_key`, `.zone_key` TEXT | str | none | `int` | UNRESOLVED (D2) |
| `.channel_key` TEXT, nullable (0/537 null in seed) | str \| null | none | `channel_key: int` (required) | UNRESOLVED: type + nullability |
| `dim_unit_master.launch_batch_id` | `launch_batch_id` | join on `unit_key` | `launch_batch_id` | DERIVED |
| `.inventory_status` (CHECK allows `LOCKED`; seed has AVAILABLE/BOOKED/SOLD) | same | none | Literal without `LOCKED` | UNRESOLVED: extend enum or reject row with DQ |
| `.unsold_days_dom` | `dom_days` | none | `unsold_days_dom` | VERIFIED_EXISTING |
| — | `is_overdue_flag` | `inventory_status='AVAILABLE' AND unsold_days_dom > overdue_threshold_days` (sc-1 = 90, [semantic_config.py:73](../../backend/vdagent_backend/re_warehouse/semantic_config.py#L73)) | `is_overdue_flag` | DERIVED |
| `.asking_price_vnd` INTEGER nullable | same | none | `int \| None` | VERIFIED_EXISTING |
| `.net_price_per_m2` INTEGER | `net_price_per_m2_vnd` | none | — (Insight reads via metric) | VERIFIED_EXISTING |
| `dm_unit_friction_diagnostics.subsidy_duration_mo` (nullable; only diagnosed units; A12-08 = null) | `subsidy_duration_mo` int \| null | left join | `subsidy_duration_mo: int` (required) | **UNAVAILABLE** for most units → Insight field must become optional (D8) |
| `dim_sales_channel.base_commission_pct` | same | join on `channel_key` | `base_commission_pct: Dec` | DERIVED (null when channel null → UNRESOLVED) |
| `dim_sales_channel.spiff_bonus_vnd` | same | join | `spiff_bonus_vnd: int \| None` | DERIVED |
| — (export only: `discount_pct`, `concession_value_vnd`, `principal_grace_mo`, `is_exclusive_lock`) | — | — | not in Insight model | UNAVAILABLE in DW |

### 5.3 Project (Insight `ProjectRow`, [contracts.py:460-468](../../agents/insight/vdagent_insight/contracts.py#L460))

| DW source | Canonical | Transform | Insight field | Class |
|---|---|---|---|---|
| `dim_project_profile.project_key` TEXT `PRJ-X` | `project_key` | none | `project_key: int` | UNRESOLVED (D2) |
| — | `project_id` | `= project_key` | `project_id` | DERIVED |
| `project_name` | same | none | same | VERIFIED_EXISTING |
| `market_id` | same | none | same | VERIFIED_EXISTING |
| `segment` (seed: `HIGH_END`, `MID_END`; schema `TODO(spec-gap)`, [schema.sql:26](../../backend/vdagent_backend/re_warehouse/schema.sql#L26)) | `segment` str | none | Literal `AFFORDABLE/MID/MID_HIGH/LUXURY` | **UNRESOLVED** — no approved mapping; do not guess (D2b) |
| `is_sales_permit_issued` 0/1 | bool | `== 1` | bool | VERIFIED_EXISTING |
| `is_bank_guarantee_issued` 0/1 | bool | `== 1` | bool | VERIFIED_EXISTING |

### 5.4 Zone (Insight `ZoneRow`, [contracts.py:472-476](../../agents/insight/vdagent_insight/contracts.py#L472))

| DW source | Canonical | Transform | Insight field | Class |
|---|---|---|---|---|
| `dim_zone_master.zone_key` TEXT `ZN-A` | `zone_key` | none | `zone_key: int` | UNRESOLVED (D2) |
| — | `zone_id` | `= zone_key` | `zone_id` | DERIVED |
| `project_key` | same | none | `project_key: int` | UNRESOLVED (D2) |
| `zone_name` | same | none | same | VERIFIED_EXISTING |

### 5.5 Diagnostics (Insight `DiagnosticRow` L516, `CauseRow` L540)

| DW source | Insight field | Transform | Class |
|---|---|---|---|
| — | `diagnostic_id` | `DIAG-{snapshot_date_key}-{unit_key}` | DERIVED |
| `snapshot_date_key`, `unit_key` | same | none (`unit_key` type per D2) | VERIFIED_EXISTING |
| `dim_unit_master.unit_code` | `unit_code` | join | DERIVED |
| `dim_project_profile.project_name`, `dim_zone_master.zone_name` | `project_name`, `zone_name` | join | DERIVED |
| `fact_unit_inventory_snapshot.unsold_days_dom` | `unsold_days_dom` | join same snapshot | DERIVED |
| `price_spread_vs_peer_pct` | same | decimal str | VERIFIED_EXISTING (A12-08 = `12.40`) |
| `ticket_size_vs_income_ratio`, `secondary_price_gap_pct`, `funnel_dropoff_rate_pct` | same | nullable | VERIFIED_EXISTING (A12-08 all null) |
| `physical_defect_penalty`, `thermal_view_penalty` | `int` (required) | DW nullable | VERIFIED_EXISTING, UNRESOLVED nullability |
| `primary_cause_code` (nullable) | `str` (required) | undiagnosed units have no row or null | UNRESOLVED nullability |
| `recommended_action` (nullable; A12-08 null) | `str` (required) | — | **UNAVAILABLE** for A12-08 → optional (D8) |
| `is_peer_sample_constrained` 0/1 | bool | `== 1` | VERIFIED_EXISTING |
| `peer_n` (`TODO(spec-gap)`, 84/537 null) | `peer_count` | rename | VERIFIED_EXISTING, semantics UNRESOLVED (A12-08 = 7) |
| `unit_diagnostic_causes.*` | `CauseRow` | `evidence_artifact_id = null` | VERIFIED_EXISTING / UNAVAILABLE (evidence id) |

### 5.6 Compare metrics (Compare `Unit.metrics`, [vh_data.py:93-104](../../agents/compare/vdagent_compare/vh_data.py#L93))

| Compare metric | DW source | Transform | Class | A12-08 @ 20260928 |
|---|---|---|---|---|
| `net_asking_price_per_m2` | `fact_unit_inventory_snapshot.net_price_per_m2` | none (VND/m²) | VERIFIED_EXISTING | 72 500 000 |
| `dom` | `.unsold_days_dom` | none (days) | VERIFIED_EXISTING | 138 |
| `inquiry_leads_30d` | `fact_sales_funnel_daily.leads` | `SUM(leads)` over `date_key ∈ (snapshot_date−29d … snapshot_date]`; if the unit has **no rows** ⇒ `null` + `METRIC_UNAVAILABLE:inquiry_leads_30d`; if the table's coverage is shorter than 30 days ⇒ limitation `WINDOW_INCOMPLETE:inquiry_leads_30d:<days>` | DERIVED | **null** (0 funnel rows for A12-08; table covers only 20260925–20260927) |
| `discount_pct` | — | — | **UNAVAILABLE** (export-only column) | null + `METRIC_UNAVAILABLE:discount_pct` |
| `subsidy_duration_mo` | `dm_unit_friction_diagnostics.subsidy_duration_mo` | left join | VERIFIED_EXISTING, sparse | null |
| (area for peers) | `dim_unit_master.net_area_m2` | D9 | VERIFIED_EXISTING | 63.02 |

The Compare hero fixture carries `inquiry_leads_30d = 3` and `discount_pct = 0` for A12-08; neither value exists in the DW
and must not appear in integration outputs.

### 5.7 Out of scope / unavailable domains

CRM customers, transactions, contracts per customer, expert reports (`docs/*.md`) — **UNAVAILABLE** in the DW.
`fact_market_macro_monthly.median_household_income_vnd` (export only) — UNAVAILABLE; Insight must read the precomputed
`ticket_size_vs_income_ratio` instead.

---

## 6. Validation constraints (all PROPOSED_NEW)

Implemented in WS1: `peer_rules.area_tolerance_ratio` (ratio in [0.05, 0.10]; `"10"` rejected as a percent; accepts
the `sc-1` JSON value `"0.10"`), `peer_rules.peer_area` (`net_area_m2` only, raises `PeerAreaUnavailable`),
store-level reference/hash/snapshot/semantic checks. Everything else in this table is still proposed.

| Rule | Where enforced | Failure |
|---|---|---|
| One APPROVED snapshot per run | Data (query builder), every consumer on read | `SPEC_ISSUE` |
| `semantic_config_version` equal across inputs | consumers | `SPEC_ISSUE` |
| Decimal strings for area/pct/ratio; int for VND | contract models | `WRONG_RESULT` |
| `input_artifact_refs` resolvable for the user | artifact store | `NO_DATA` |
| `content_hash` of ref equals stored | consumers (`expected_hash`) | `WRONG_RESULT` |
| No float in payload | store (existing) | tool error |
| Units in scope only | `re_run_query` (existing) + consumer re-check | `NO_ACCESS` |

## 7. Limitation codes (PROPOSED_NEW registry; codes in use are listed in AGENT_CONTRACT_MATRIX §3)

WS5 adds `UPSTREAM_FAILED:<agent>` on a step whose `any` dependency failed (IMPLEMENTED) and persists every
step's limitations in `run_state@1`.


| Code | Meaning | Status impact |
|---|---|---|
| `METRIC_UNAVAILABLE:<metric>` | metric has no DW source or null for the subject | PARTIAL |
| `WINDOW_INCOMPLETE:<metric>:<days>` | time window coverage below requirement | PARTIAL |
| `PEER_AREA_UNAVAILABLE:<n>` | candidates excluded for null `net_area_m2` | PARTIAL |
| `PEER_SAMPLE_CONSTRAINED` | peers < `min_group_size` | PARTIAL |
| `CONFIG_PENDING:<key>` | semantic key not APPROVED | PARTIAL |
| `UPSTREAM_FAILED:<agent>` | an upstream step failed; output built without it | PARTIAL |
| `SYNTHETIC_SOURCE:net_area_m2` | area derived by fixed ratio in the mock (DQ-1) | informational (VALID allowed) |

## 8. Examples

Valid `dataset` draft (abbreviated):
```json
{"artifact_type":"dataset","schema_version":"re_dataset@1","status":"VALID",
 "producer":{"agent":"data","agent_version":"0.2.0"},
 "snapshot_refs":["SNAP-2026-09-28"],"semantic_config_version":"sc-1",
 "source_refs":["re:dim_unit_master","re:fact_unit_inventory_snapshot"],
 "limitations":["SYNTHETIC_SOURCE:net_area_m2"],
 "payload":{"snapshot":{"snapshot_id":"SNAP-2026-09-28","snapshot_date_key":20260928,"semantic_config_version":"sc-1"},
  "tables":{"dim_unit_master":[{"unit_key":"U-PRJ-X-A12-08","unit_code":"A12-08","net_area_m2":"63.02","area_m2":"68.50"}]}}}
```

Invalid examples and expected rejection:

| Payload fragment | Reason |
|---|---|
| `"snapshot_refs":["SNAP-2026-09-29"]` | snapshot is DRAFT |
| `"snapshot_refs":["SNAP-2026-08-31","SNAP-2026-09-28"]` | more than one snapshot |
| `"net_area_m2": 63.02` (JSON float) in a direct store write | float rejected |
| `"inquiry_leads_30d": 0` for A12-08 | fabricated value; must be `null` + limitation |
| `"status":"PARTIAL","limitations":[]` | existing validator |
| area band computed from `area_m2` | violates D9 (detected by C-CMP-02) |

## 9. WS6 `report@1` (IMPLEMENTED, VERIFIED offline)

Producer: `report`; schema: `report@1`; input artifacts: one canonical `dataset` plus present `insight`, `peer_definition`, `comparison`, and zero or more `chart_spec` refs. All are hash-pinned and must share the caller, `SNAP-2026-09-28`, `sc-1`, and the same pinned dataset. A comparison additionally pins the supplied peer definition.

Payload fields in use: `title`, `sections` (exactly six), `markdown`, `statements[]` (`statement_id`, `section`, `text`, `value_exact`, `source_ref`), `charts[]`, `tables[]`, `actions`, `validation` (`result`, counts for statements/chart bindings/charts), and `delivery.report_id`. `source_ref` is `<artifact_id>@<version>#<RFC6901-pointer>`. `input_artifact_refs` contains the dataset and every present analytical/chart input. `limitations` are preserved; optional missing upstream artifacts produce a PARTIAL report.

The producer never calculates a report number. Before `save_report` and `artifact_put`, it re-resolves every statement and each `chart_spec.bindings[]` exact value from its source ref and requires a Vega-Lite `$schema`. Broken/missing evidence fails `EVIDENCE_INVALID`; no saved report or report artifact is written. Saved markdown may contain only version-pinned `{{chart_spec:<id>@<version>}}` shared-artifact embeds; the backend validates type and user ownership.

> WS7 F-02 resolved: verify artifacts with `artifact_store.verify`; a SUPERSEDED version verifies against its status at write time, and hashes are never rewritten. F-08: Data artifacts carry no out-of-scope row counts (`hidden_rows` removed).

> `run_state@1`: `payload.plan.provenance` (planner, model, prompt_version, llm_calls, latency_ms, llm_plan) is present only for LLM-planned runs. Deterministic plans are recorded exactly as before.
