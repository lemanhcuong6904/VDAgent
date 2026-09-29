"""T1 semantic compiler (build spec 02 §6): metrics, dimensions and filters by name → SQL + lineage.

The LLM only picks names; this code writes the SQL. Every metric returns `<name>__num` and `<name>__den`
(integers) plus the group size `n`; the division happens in Decimal later (DEC-036). Config thresholds stay as
`:key` placeholders until `render`, so the linter sees no literal thresholds.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from vdagent_data.semantic.loader import LAYER, Layer

_CFG = re.compile(r"\{cfg\.([a-z_]+)\}")
_PLACEHOLDER = re.compile(r":([a-z_][a-z0-9_]*)\b")

# scope filter key → column of the base query
SCOPE_COLUMNS = {"project_key": "f.project_key", "zone_key": "f.zone_key", "unit_key": "f.unit_key"}


@dataclass(frozen=True)
class CompiledQuery:
    sql: str  # with :key placeholders
    config_keys: tuple[str, ...]
    lineage: dict[str, Any] = field(default_factory=dict)

    @property
    def sql_hash(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def _quote(values: list[str]) -> str:
    return "(" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + ")"


def _placeholders(sql: str) -> str:
    return _CFG.sub(lambda m: f":{m.group(1)}", sql)


def compile_t1(
    metrics: list[str],
    group_by: list[str],
    filters: list[str],
    *,
    scope_filters: dict[str, list[str]] | None = None,
    layer: Layer = LAYER,
) -> CompiledQuery:
    """KeyError for a name the layer does not define."""
    selects: list[str] = []
    for dim in group_by:
        selects.append(f"{layer.dimensions[dim].column} AS {dim}")
    for name in metrics:
        metric = layer.metrics[name]
        selects.append(f"{metric.numerator} AS {name}__num")
        if metric.denominator is not None:
            selects.append(f"{metric.denominator} AS {name}__den")
    selects.append("COUNT(*) AS n")
    where = [f"({layer.filters[f].sql})" for f in filters]
    for key, values in sorted((scope_filters or {}).items()):
        where.append(f"{SCOPE_COLUMNS[key]} IN {_quote(values)}")
    sql = f"SELECT {', '.join(selects)} FROM {layer.base}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group_by:
        dims = ", ".join(layer.dimensions[d].column for d in group_by)
        sql += f" GROUP BY {dims} ORDER BY {dims}"
    sql = _placeholders(sql)
    keys = tuple(sorted(set(_PLACEHOLDER.findall(sql))))
    lineage = {
        "tier": "T1",
        "formula_ids": {m: layer.metrics[m].formula_id for m in metrics},
        "filters": list(filters),
        "group_by": list(group_by),
        "scope_filters": {k: list(v) for k, v in sorted((scope_filters or {}).items())},
        "semantic_version": layer.semantic_version,
    }
    return CompiledQuery(sql=sql, config_keys=keys, lineage=lineage)


def render(sql: str, config: dict[str, Any]) -> str:
    """Replace `:key` placeholders with integer config values (KeyError if missing, ValueError if not an integer)."""

    def value(match: re.Match[str]) -> str:
        raw = config[match.group(1)]
        if isinstance(raw, bool) or not isinstance(raw, (int, str)):
            raise ValueError(f"config {match.group(1)} must be an integer")
        return str(int(raw))

    return _PLACEHOLDER.sub(value, sql)
