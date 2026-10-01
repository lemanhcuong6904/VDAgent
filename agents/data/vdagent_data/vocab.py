"""The names a contract-v1.0 step may use (SPEC §7.4): metrics, dimensions, filters, attributes, context groups.

The Orchestrator's catalog publishes some of these names (`contracts/vdagent_contracts/catalogs/data.json`) and the steps
already in use spell others (`dom_days`, `net_price_per_m2_vnd`, ...): Data accepts both, so a plan written from either
list is served. A name outside this module is `SPEC_INVALID`; nothing is guessed. Thresholds never appear here (§7.4): a
filter like `slow_moving` names a rule whose number is read from `semantic_config` when the step runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Statistic = Literal["count", "mean", "median", "ratio"]


@dataclass(frozen=True)
class MetricV1:
    unit: str
    statistic: Statistic
    calculation_ref: str
    source: str | None = None  # "table.column" for the ones that read one column; None for counts and ratios
    provisional: bool = False  # the definition is not yet approved by the DATA team (SPEC §6.4)
    needs: str | None = None  # a semantic_config key that must be APPROVED (else CONFIG_MISSING)
    optional_column: str | None = None  # read only if the inventory rows carry it (else null + limitation)


METRICS_V1: dict[str, MetricV1] = {
    # names of the Orchestrator's catalog
    "unit_count": MetricV1("COUNT", "count", "calc_unit_count@1"),
    "avg_dom_unsold": MetricV1("DAY", "mean", "calc_avg_dom_unsold@1", "fact_unit_inventory_snapshot.unsold_days_dom"),
    "slow_moving_count": MetricV1("COUNT", "count", "calc_slow_moving_count@1", needs="overdue_threshold_days"),
    "slow_moving_rate": MetricV1("PCT", "ratio", "calc_slow_moving_rate@1", needs="overdue_threshold_days"),
    "avg_net_price_per_m2": MetricV1("VND_PER_M2", "mean", "calc_avg_net_price_per_m2@1", "fact_unit_inventory_snapshot.net_price_per_m2"),
    "absorption_rate": MetricV1("PCT", "ratio", "calc_absorption_rate@1", provisional=True),
    # names the single-unit steps use (medians over the group)
    "dom_days": MetricV1("DAY", "median", "calc_dom_days@1", "fact_unit_inventory_snapshot.unsold_days_dom"),
    "net_price_per_m2_vnd": MetricV1("VND_PER_M2", "median", "calc_net_price_per_m2@1", "fact_unit_inventory_snapshot.net_price_per_m2"),
    "asking_price_vnd": MetricV1("VND", "median", "calc_asking_price@1", "fact_unit_inventory_snapshot.asking_price_vnd"),
    "net_area_m2": MetricV1("M2", "median", "calc_net_area_m2@1", "dim_unit_master.net_area_m2"),
    "discount_pct": MetricV1("PCT", "median", "calc_discount_pct@1", "fact_unit_inventory_snapshot.discount_pct", optional_column="discount_pct"),
    "subsidy_duration_mo": MetricV1("COUNT", "median", "calc_subsidy_duration@1", "fact_unit_inventory_snapshot.subsidy_duration_mo",
                                    optional_column="subsidy_duration_mo"),
}

# the metrics of a set of units when the step only asks for the units (fetch_units): summary rows next to the tables
SET_SUMMARY_METRICS = ("unit_count", "avg_dom_unsold", "avg_net_price_per_m2", "slow_moving_count")

# dimension name → unit-row field ("market" is the project's market, looked up from the project profile)
DIMENSIONS: dict[str, str] = {
    "project": "project_key", "zone": "zone_key", "market": "market_id", "floor_band": "floor_band",
    "balcony_orientation": "balcony_orientation", "view_primary_type": "view_primary_type", "unit_type": "unit_type",
    "launch_batch": "launch_batch_id", "channel": "channel_key", "inventory_status": "inventory_status",
    # the column spellings the single-unit steps use
    "project_key": "project_key", "zone_key": "zone_key", "launch_batch_id": "launch_batch_id",
}

FILTERS = ("released", "available", "booked", "sold", "slow_moving")

ATTRIBUTES = (
    "unit_code", "zone", "unit_type", "area_m2", "net_area_m2", "floor_band", "floor_no", "balcony_orientation", "view_primary_type",
    "view_type", "launch_batch", "inventory_status", "unsold_days_dom", "asking_price_vnd", "net_price_per_m2",
)

CONTEXT_GROUPS = ("price", "funnel", "secondary", "macro", "infra")
STATUS_OF_FILTER = {"available": "AVAILABLE", "booked": "BOOKED", "sold": "SOLD"}


def unknown_names(kind: str, names: list[str], allowed: tuple[str, ...] | dict[str, object]) -> list[str]:
    known = set(allowed)
    return [f"{kind} `{n}`" for n in names if n not in known]
