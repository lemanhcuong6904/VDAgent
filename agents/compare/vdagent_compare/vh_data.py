"""Read the synthetic VHOP CSV pack as a versioned, immutable Compare input package.

The CSV pack belongs to the DATA team and is not committed with this plugin (see
`default_data_root`); the A12-08 hero fixture ships in `fixtures/`. This module never queries the warehouse or
computes canonical price/DOM values; it only maps columns and sums the already recorded
daily inquiry counts for the requested 30-day window.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Unit:
    unit_id: str
    unit_code: str
    project_id: str
    zone_id: str
    unit_type: str
    area_m2: Decimal
    floor_band: str
    balcony_orientation: str
    view_type: str
    status: str
    launch_batch_id: str
    metrics: Mapping[str, Decimal | None]

    def attribute(self, name: str) -> str | Decimal:
        return getattr(self, name)


@dataclass(frozen=True)
class DataPackage:
    name: str
    snapshot_id: str
    semantic_version: str
    snapshot_date: str
    metric_artifact_id: str
    dq_artifact_id: str
    units: tuple[Unit, ...]
    approved_config: Mapping[str, str]

    def in_scope(self, unit: Unit, scope: Mapping[str, object]) -> bool:
        projects = scope.get("allowedProjectIds") or []
        zones = scope.get("allowedZoneIds") or []
        return (not projects or unit.project_id in projects) and (not zones or unit.zone_id in zones)

    def resolve_unit(self, ref: Mapping[str, str], scope: Mapping[str, object]) -> tuple[Unit | None, str | None, list[Unit]]:
        key = ref.get("entityId")
        code = ref.get("entityCode")
        hits = [u for u in self.units if u.unit_id == key] if key else [
            u for u in self.units if u.unit_code.upper() == str(code).upper()
        ]
        if key and code and hits and any(u.unit_code.upper() != str(code).upper() for u in hits):
            return None, "INVALID_INPUT", []
        if not hits and code and not key:
            choices = sorted(
                (u for u in self.units if u.unit_code.upper().startswith(str(code).upper()) and self.in_scope(u, scope)),
                key=lambda u: u.unit_code,
            )
            if choices:
                return None, "CLARIFICATION_NEEDED", choices
        if not hits:
            return None, "SUBJECT_NOT_FOUND", []
        if len(hits) > 1:
            return None, "SUBJECT_AMBIGUOUS", [u for u in hits if self.in_scope(u, scope)][:10]
        if not self.in_scope(hits[0], scope):
            return None, "PERMISSION_DENIED", []
        return hits[0], None, []

    def candidate_pool(self, subject: Unit, scope: Mapping[str, object]) -> tuple[list[Unit], int]:
        rows = [u for u in self.units if u.project_id == subject.project_id and u.launch_batch_id == subject.launch_batch_id]
        allowed = [u for u in rows if self.in_scope(u, scope)]
        return allowed, len(rows) - len(allowed)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _number(value: str | int | float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None and str(value) != "" else None


def _metric_values(row: Mapping[str, object], leads: int | None = None) -> dict[str, Decimal | None]:
    dom = _number(row.get("unsold_days_dom", row.get("dom")))
    return {
        "net_asking_price_per_m2": _number(row.get("net_price_per_m2", row.get("net_asking_price_per_m2"))),
        "asking_price_per_m2": _number(row.get("asking_price_per_m2")),
        "asking_price_vnd": _number(row.get("asking_price_vnd")),
        "dom": dom,
        "unsold_days": dom,
        "inquiry_leads_30d": Decimal(leads) if leads is not None else _number(row.get("inquiry_leads_30d")),
        "discount_pct": _number(row.get("discount_pct")),
        "subsidy_duration_mo": _number(row.get("subsidy_duration_mo")),
    }


def load_csv_package(root: Path) -> DataPackage:
    export = root / "export"
    manifest = _rows(export / "snapshot_manifest.csv")[0]
    snapshot = manifest["snapshot_id"]
    latest_key = int(manifest["snapshot_date"].replace("-", ""))
    project_ids = {r["project_key"]: r["project_id"] for r in _rows(export / "dim_project_profile.csv")}
    zone_ids = {r["zone_key"]: r["zone_id"] for r in _rows(export / "dim_zone_master.csv")}
    dimensions = {r["unit_key"]: r for r in _rows(export / "dim_unit_master.csv")}
    facts = {
        r["unit_key"]: r for r in _rows(export / "fact_unit_inventory_snapshot.csv")
        if int(r["snapshot_date_key"]) == latest_key
    }
    first_day = int((date.fromisoformat(manifest["snapshot_date"]) - timedelta(days=29)).strftime("%Y%m%d"))
    leads: dict[str, int] = {}
    for row in _rows(export / "fact_sales_funnel_daily.csv"):
        day = int(row["date_key"])
        if first_day <= day <= latest_key:
            leads[row["unit_key"]] = leads.get(row["unit_key"], 0) + int(row["inquiry_leads_count"])
    config = {
        r["config_key"]: r["config_value"]
        for r in _rows(export / "semantic_config.csv")
        if r["approval_status"].upper() == "APPROVED" and r["semantic_version"] == manifest["semantic_version"]
    }
    units = []
    for unit_key, row in dimensions.items():
        fact = facts.get(unit_key)
        if fact is None:
            continue
        units.append(Unit(
            unit_id=row["unit_id"], unit_code=row["unit_code"],
            project_id=project_ids[row["project_key"]], zone_id=zone_ids[row["zone_key"]],
            unit_type=row["unit_type"], area_m2=Decimal(row["net_area_m2"]),
            floor_band=row["floor_band"], balcony_orientation=row["balcony_orientation"],
            view_type=row["view_primary_type"], status=fact["inventory_status"].lower(),
            launch_batch_id=fact["launch_batch_id"],
            metrics=_metric_values(fact, leads.get(unit_key, 0)),
        ))
    return DataPackage(
        name="vhop_csv", snapshot_id=snapshot, semantic_version=manifest["semantic_version"],
        snapshot_date=manifest["snapshot_date"], metric_artifact_id="vhop_metric_" + snapshot,
        dq_artifact_id="vhop_dq_" + snapshot, units=tuple(units), approved_config=config,
    )


HERO_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hero_a12_08.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
# Where the Data team's pack may live, in order: the path Data publishes it under, then local copies.
PACK_LOCATIONS = ("warehouse/vhop", "var/vhop", "data/vhop")


def load_hero_package(root: Path | None = None) -> DataPackage:
    """The approved A12-08 fixture (spec §5.1). It ships with the plugin; `root` is ignored."""
    raw = json.loads(HERO_FIXTURE.read_text(encoding="utf-8"))
    units = tuple(Unit(
        unit_id=row["unit_id"], unit_code=row["unit_code"], project_id=row["project_id"],
        zone_id=row["zone_id"], unit_type=row["unit_type"], area_m2=Decimal(str(row["area_m2"])),
        floor_band=row["floor_band"], balcony_orientation=row["balcony_orientation"],
        view_type=row["view_type"], status=row["status"], launch_batch_id=row["launch_batch_id"],
        metrics=_metric_values(row),
    ) for row in raw["units"])
    meta = raw["upstream"]
    return DataPackage(
        name="hero_fixture", snapshot_id=meta["manifest"]["snapshot_id"],
        semantic_version=meta["manifest"]["semantic_version"], snapshot_date="2026-06-30",
        metric_artifact_id=meta["metric_artifact"]["id"],
        dq_artifact_id=meta["dq_artifact"]["id"], units=units,
        approved_config={"peer_area_tolerance_pct": "10", "min_peer_count": "5", "overdue_threshold_days": "90"},
    )


def default_data_root(repo_root: Path | None = None) -> Path:
    """The CSV pack: `VDAGENT_VHOP_DATA_DIR`, else the first of `PACK_LOCATIONS` holding a pack.

    Locations are tried under the repository root, then under the working directory.
    """
    configured = os.getenv("VDAGENT_VHOP_DATA_DIR")
    if configured:
        return Path(configured).resolve()
    bases = [repo_root or REPO_ROOT, Path.cwd()]
    tried = [base / location for base in bases for location in PACK_LOCATIONS]
    for candidate in tried:
        if (candidate / "export" / "snapshot_manifest.csv").exists():
            return candidate.resolve()
    raise FileNotFoundError(
        "VHOP CSV pack not found; set VDAGENT_VHOP_DATA_DIR or put it at one of: "
        + ", ".join(location for location in PACK_LOCATIONS)
    )


def is_hero_ref(ref: Mapping[str, str]) -> bool:
    key = (ref.get("entityCode") or ref.get("entityId") or "").upper()
    return key.startswith(("A12-", "A10-", "A14-", "B09-", "B11-", "ZN-A", "ZN-B", "PRJ-X")) or key in {
        "U812", "U801", "U815", "U820", "U833", "U841"}


def load_package_for(ref: Mapping[str, str], root: Path | None = None) -> DataPackage:
    if is_hero_ref(ref):
        return load_hero_package()
    return load_csv_package(root or default_data_root())
