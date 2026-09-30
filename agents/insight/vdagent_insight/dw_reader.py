"""Insight's view of the canonical Data artifacts (re_dataset@1 of `re_warehouse`, WS3, D1/D2/D8).

`DwArtifactReader` is an `ExportArtifactReader` whose pack is built from one Data `dataset` artifact instead of the
export CSV folder, so the pipeline (steps 0–10) and its input artifacts (metric / dq / dataset built by
export_reader.py) stay exactly the same. Mapping DW row → Insight row (docs/integration/CANONICAL_DATA_CONTRACT.md §5):

- keys stay the DW TEXT keys; `unit_id` / `project_id` / `zone_id` = the key (the DW has no separate id);
- `net_area_m2` through `peer_rules.peer_area` (D9); `asking_price_per_m2` has no DW column → null;
- `floor_no` → `floor_number`; `launch_batch_id` from `dim_unit_master`; `is_overdue_flag` = AVAILABLE and
  `unsold_days_dom` > `overdue_threshold_days` of the semantic config; commission from `dim_sales_channel`;
- `subsidy_duration_mo` from the diagnostics mart (null when absent, D8);
- diagnostics: only rows with a `primary_cause_code` (the DW marks undiagnosed units with NULL);
  `diagnostic_id` = `DIAG-<snapshot_date_key>-<unit_key>`; `peer_count` = `peer_n`; unit/project/zone names joined;
- `segment` is kept raw (D2b BLOCKED); no market context (the dataset carries no macro rows).

Artifact ids are `<Data artifact id>~insight`, so every evidence reference maps back to a stored Data artifact.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from vdagent_contracts.peer_rules import peer_area
from vdagent_contracts.step_inputs import DataInputs

from .artifacts import content_hash
from .contracts import (
    AnalysisScope,
    CauseRow,
    DiagnosticRow,
    InputArtifact,
    InputArtifactType,
    InventoryRow,
    ProjectRow,
    UnitRow,
    ZoneRow,
)
from .export_reader import ExportArtifactReader, Manifest, _Pack, build_pack
from .settings import SemanticConfig

SUFFIX = "~insight"


def store_id(local_id: str) -> str:
    """The Data artifact id behind one of this reader's artifact ids (or the id itself)."""
    return local_id.split(SUFFIX, 1)[0]


def _pack(inputs: DataInputs, cfg: SemanticConfig) -> _Pack:
    payload = inputs.dataset["payload"]
    snap = payload["snapshot"]
    tables: dict[str, list[dict[str, Any]]] = payload["tables"]
    units_raw = tables["dim_unit_master"]
    unit_by_key = {u["unit_key"]: u for u in units_raw}
    projects_raw = {p["project_key"]: p for p in tables["dim_project_profile"]}
    zones_raw = {z["zone_key"]: z for z in tables["dim_zone_master"]}
    channels = {c["channel_key"]: c for c in tables.get("dim_sales_channel", [])}
    inventory_raw = {r["unit_key"]: r for r in tables["fact_unit_inventory_snapshot"]}
    diagnosed = {r["unit_key"]: r for r in tables["dm_unit_friction_diagnostics"] if r["primary_cause_code"] is not None}
    threshold = cfg.params.overdue_threshold_days

    projects = [ProjectRow.model_validate({
        "project_key": p["project_key"], "project_id": p["project_key"], "project_name": p["project_name"],
        "market_id": p["market_id"], "segment": p["segment"],
        "is_sales_permit_issued": bool(p["is_sales_permit_issued"]), "is_bank_guarantee_issued": bool(p["is_bank_guarantee_issued"]),
    }) for p in projects_raw.values()]  # fmt: skip
    zones = [ZoneRow.model_validate({
        "zone_key": z["zone_key"], "zone_id": z["zone_key"], "project_key": z["project_key"], "zone_name": z["zone_name"],
    }) for z in zones_raw.values()]  # fmt: skip
    units = [UnitRow.model_validate({
        "unit_key": u["unit_key"], "unit_id": u["unit_key"], "unit_code": u["unit_code"], "project_key": u["project_key"],
        "zone_key": u["zone_key"], "unit_type": u["unit_type"], "net_area_m2": peer_area(u), "floor_number": u["floor_no"],
        "floor_band": u["floor_band"],
        "balcony_orientation": u["balcony_orientation"], "view_primary_type": u["view_primary_type"],
    }) for u in units_raw]  # fmt: skip
    inventory = []
    for key, r in inventory_raw.items():
        channel = channels.get(r["channel_key"], {})
        diag = diagnosed.get(key)
        inventory.append(InventoryRow.model_validate({
            "snapshot_date_key": r["snapshot_date_key"], "unit_key": key, "project_key": r["project_key"],
            "zone_key": r["zone_key"], "channel_key": r["channel_key"], "launch_batch_id": unit_by_key[key]["launch_batch_id"],
            "inventory_status": r["inventory_status"], "unsold_days_dom": r["unsold_days_dom"],
            "is_overdue_flag": r["inventory_status"] == "AVAILABLE" and r["unsold_days_dom"] > threshold,
            "asking_price_vnd": r["asking_price_vnd"], "asking_price_per_m2": None,  # no DW column (D8: null, FIELD_UNAVAILABLE)
            "subsidy_duration_mo": diag["subsidy_duration_mo"] if diag else None,
            "base_commission_pct": channel.get("base_commission_pct"), "spiff_bonus_vnd": channel.get("spiff_bonus_vnd"),
        }))  # fmt: skip
    mart = []
    for key, d in diagnosed.items():
        unit = unit_by_key[key]
        mart.append(DiagnosticRow.model_validate({
            "diagnostic_id": f"DIAG-{d['snapshot_date_key']}-{key}", "snapshot_date_key": d["snapshot_date_key"],
            "unit_key": key, "unit_code": unit["unit_code"],
            "project_name": projects_raw[unit["project_key"]]["project_name"], "zone_name": zones_raw[unit["zone_key"]]["zone_name"],
            "unsold_days_dom": inventory_raw[key]["unsold_days_dom"],
            "price_spread_vs_peer_pct": d["price_spread_vs_peer_pct"], "ticket_size_vs_income_ratio": d["ticket_size_vs_income_ratio"],
            "physical_defect_penalty": d["physical_defect_penalty"], "thermal_view_penalty": d["thermal_view_penalty"],
            "secondary_price_gap_pct": d["secondary_price_gap_pct"], "funnel_dropoff_rate_pct": d["funnel_dropoff_rate_pct"],
            "primary_cause_code": d["primary_cause_code"], "recommended_action": d["recommended_action"],
            "is_peer_sample_constrained": bool(d["is_peer_sample_constrained"]), "peer_count": d["peer_n"],
        }))  # fmt: skip
    causes = [CauseRow.model_validate({
        "diagnostic_id": f"DIAG-{c['snapshot_date_key']}-{c['unit_key']}", "cause_code": c["cause_code"],
        "unit_key": c["unit_key"], "snapshot_date_key": c["snapshot_date_key"], "severity_rank": c["severity_rank"],
        "attribution_score": c["attribution_score"], "evidence_artifact_id": None,
    }) for c in tables["unit_diagnostic_causes"] if c["unit_key"] in diagnosed]  # fmt: skip
    manifest = Manifest(snap["snapshot_id"], snap["semantic_config_version"], snap["snapshot_date"])
    return build_pack(manifest, projects=projects, zones=zones, units=units, inventory=inventory, mart=mart,
                      causes=causes, macro=[])


class DwArtifactReader(ExportArtifactReader):
    """The export reader over a pack built from Data artifacts; never touches the export folder."""

    def __init__(self, inputs: DataInputs, cfg: SemanticConfig) -> None:
        self._cfg = cfg
        self._prepared: dict[str, InputArtifact] = {}
        self._inputs = inputs
        self._pack = _pack(inputs, cfg)

    async def _data(self) -> _Pack:
        assert self._pack is not None
        return self._pack

    def _artifact(self, pack: _Pack, kind: InputArtifactType, scope_key: str, payload: BaseModel) -> InputArtifact:
        source = {"metric": self._inputs.metric, "dq": self._inputs.dq}.get(kind, self._inputs.dataset)
        data = payload.model_dump(mode="json")
        art = InputArtifact(
            artifact_id=f"{source['artifact_id']}{SUFFIX}" + (":market_context" if kind == "market_context" else ""), artifact_type=kind, version=1, status="VALID",
            snapshot_id=pack.manifest.snapshot_id, semantic_config_version=pack.manifest.semantic_version,
            content_hash=content_hash(data), payload=data,
        )
        self._prepared[art.artifact_id] = art
        return art

    async def prepare_required(self, scope: AnalysisScope) -> list[InputArtifact]:
        """metric, dq and dataset for `scope` (no market_context: the dataset has no macro rows)."""
        return [a for a in await self.prepare(scope) if a.artifact_type != "market_context"]
