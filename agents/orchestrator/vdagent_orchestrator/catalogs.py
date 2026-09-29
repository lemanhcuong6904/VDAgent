"""Catalog registry (build spec 01 §5, DEC-023): every worker catalog, cached by version."""

from __future__ import annotations

from dataclasses import dataclass

from vdagent_contracts.catalog import AgentCatalog, CatalogOperation
from vdagent_contracts.catalogs import load_all
from vdagent_contracts.intents import TaskKind, served_task_kinds


@dataclass(frozen=True)
class CatalogRegistry:
    catalogs: dict[str, AgentCatalog]

    @staticmethod
    def load() -> CatalogRegistry:
        catalogs = load_all()
        return _cached(tuple(sorted((agent, c.catalog_version) for agent, c in catalogs.items())), catalogs)

    def versions(self) -> dict[str, str]:
        return {agent: c.catalog_version for agent, c in self.catalogs.items()}

    def operation(self, agent: str, operation: str) -> CatalogOperation:
        return self.catalogs[agent].operation(operation)

    def served_kinds(self) -> set[TaskKind]:
        return served_task_kinds(self.catalogs.values())

    def producers_of(self, kind: str) -> list[tuple[str, str]]:
        return [(a, op.operation) for a, c in self.catalogs.items() for op in c.operations if kind in op.produces]

    def vocabulary(self) -> dict[str, list[str]]:
        vocab = self.catalogs["data"].vocabulary
        return {"metrics": [v.name for v in vocab.metrics], "dimensions": [v.name for v in vocab.dimensions],
                "filters": [v.name for v in vocab.filters], "attributes": [v.name for v in vocab.attributes]}


_REGISTRIES: dict[tuple[tuple[str, str], ...], CatalogRegistry] = {}


def _cached(key: tuple[tuple[str, str], ...], catalogs: dict[str, AgentCatalog]) -> CatalogRegistry:
    if key not in _REGISTRIES:
        _REGISTRIES[key] = CatalogRegistry(catalogs)
    return _REGISTRIES[key]


__all__ = ["CatalogRegistry"]
