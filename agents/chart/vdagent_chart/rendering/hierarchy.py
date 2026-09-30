from __future__ import annotations

from typing import Any, Mapping

from .common import encoding, field, figure, layout, records


def render_treemap(spec: Mapping[str, Any]) -> dict[str, Any]:
    spec_encoding = encoding(spec)
    spec_records = records(spec)
    path = spec_encoding.get("path")
    path_fields = [str(item) for item in path] if isinstance(path, list) else ["label"]
    value_field = field(spec_encoding, "value", "value")
    labels: list[str] = []
    parents: list[str] = []
    values: list[float | int | None] = []
    index: dict[tuple[str, str], int] = {}
    for record in spec_records:
        parent = ""
        for path_field in path_fields:
            label = str(record.get(path_field))
            key = (label, parent)
            if key not in index:
                index[key] = len(labels)
                labels.append(label)
                parents.append(parent)
                values.append(None)
            parent = label
        leaf_parent = str(record.get(path_fields[-2])) if len(path_fields) > 1 else ""
        leaf = str(record.get(path_fields[-1]))
        values[index[(leaf, leaf_parent)]] = record.get(value_field)
    values = [0 if value is None else value for value in values]
    return figure([{"type": "treemap", "labels": labels, "parents": parents, "values": values}], layout(spec))
