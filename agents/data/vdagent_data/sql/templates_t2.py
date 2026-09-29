"""T2 verified templates (build spec 02 §6): SQL approved by the Data Analyst, parameters validated before rendering.

Thresholds stay `:key` placeholders (rendered from semantic_config after the linter); the linter injects snapshot and
RBAC filters as for any query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-._]{0,63}$")


@dataclass(frozen=True)
class Template:
    id: str
    sql: str
    params: tuple[str, ...]
    reviewer: str  # who approved it
    description: str


UNIT_COLUMNS = (
    "f.unit_key, m.unit_code, p.project_key, z.zone_key, z.zone_name AS zone, m.unit_type, m.area_m2, m.floor_no,"
    " m.floor_band, m.balcony_orientation, m.view_primary_type, m.launch_batch_id AS launch_batch, f.inventory_status,"
    " f.unsold_days_dom, f.asking_price_vnd, f.net_price_per_m2, f.release_date, f.sold_date, f.snapshot_date"
)
BASE = (
    "fact_unit_inventory_snapshot f JOIN dim_unit_master m ON m.unit_key = f.unit_key"
    " JOIN dim_zone_master z ON z.zone_key = f.zone_key JOIN dim_project_profile p ON p.project_key = f.project_key"
)
# Adjacent launch batches of the target, same market (DEC-039; the Compare spec owns the real peer rule).
_PEER_POOL = (
    f" FROM {BASE} WHERE f.unit_key <> '{{target_unit_key}}'"
    " AND p.market_id = (SELECT p2.market_id FROM dim_unit_master m2 JOIN dim_project_profile p2"
    " ON p2.project_key = m2.project_key WHERE m2.unit_key = '{target_unit_key}')"
    " AND ABS(CAST(SUBSTR(m.launch_batch_id, 4) AS INTEGER) - (SELECT CAST(SUBSTR(m3.launch_batch_id, 4) AS INTEGER)"
    " FROM dim_unit_master m3 WHERE m3.unit_key = '{target_unit_key}')) <= 1"
)

TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template(
            id="units_with_diagnostics_v1",
            sql=(
                f"SELECT {UNIT_COLUMNS}, p.is_sales_permit_issued, p.is_bank_guarantee_issued, d.primary_cause_code,"
                " d.price_spread_vs_peer_pct, d.is_peer_sample_constrained, d.peer_n, d.physical_defect_penalty,"
                " d.thermal_view_penalty, d.subsidy_duration_mo, d.secondary_price_gap_pct, d.ticket_size_vs_income_ratio,"
                " d.funnel_dropoff_rate_pct, d.west_facing_exposure_pct, d.recommended_action"
                f" FROM {BASE} LEFT JOIN dm_unit_friction_diagnostics d ON d.unit_key = f.unit_key"
                " AND d.snapshot_date_key = f.snapshot_date_key{where} ORDER BY m.unit_code"
            ),
            params=("where",),
            reviewer="data-analyst (seed)",
            description="Căn trong phạm vi kèm mart chẩn đoán",
        ),
        Template(
            id="unit_causes_v1",
            sql=(
                "SELECT c.unit_key, c.cause_code, c.severity_rank, c.attribution_score FROM unit_diagnostic_causes c"
                " JOIN fact_unit_inventory_snapshot f ON f.unit_key = c.unit_key"
                " AND f.snapshot_date_key = c.snapshot_date_key{where} ORDER BY c.unit_key, c.severity_rank"
            ),
            params=("where",),
            reviewer="data-analyst (seed)",
            description="Bảng cầu nguyên nhân của các căn trong phạm vi",
        ),
        Template(
            id="target_unit_v1",
            sql=f"SELECT {UNIT_COLUMNS} FROM {BASE} WHERE f.unit_key = '{{target_unit_key}}'",
            params=("target_unit_key",),
            reviewer="data-analyst (seed)",
            description="Căn mục tiêu",
        ),
        Template(
            id="peer_candidates_v1",
            sql=f"SELECT {UNIT_COLUMNS}{_PEER_POOL} ORDER BY m.unit_code",
            params=("target_unit_key",),
            reviewer="data-analyst (seed)",
            description="Ứng viên peer: cùng thị trường, đợt mở bán liền kề",
        ),
        Template(
            id="peer_candidate_keys_v1",
            sql=f"SELECT f.unit_key{_PEER_POOL}",
            params=("target_unit_key",),
            reviewer="data-analyst (seed)",
            description="Đếm ứng viên (kể cả ngoài quyền) để báo permissionFilteredCount",
        ),
    )
}


def render_template(template_id: str, params: dict[str, str]) -> str:
    """KeyError for an unknown template or missing parameter; ValueError for an unsafe key value."""
    template = TEMPLATES[template_id]
    values: dict[str, str] = {}
    for name in template.params:
        value = params[name]
        if name != "where" and not _KEY.fullmatch(value):
            raise ValueError(f"unsafe value for {name}")
        values[name] = value
    return template.sql.format(**values)
