"""The package dependency rule, checked on every module's imports.

Each unit (a package, or the top-level `config` / `app` module) may import only the units listed
for it; `app` is the composition root and imports everything. Across units, code imports only the
names a package exports in its `__init__.__all__`.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import vdagent_backend

ROOT = Path(vdagent_backend.__file__).resolve().parent

ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "config": {"core"},
    "persistence": {"core"},
    "plugins": {"core", "config"},
    "warehouse": {"core"},
    "scopes": {"core", "persistence"},
    "re_warehouse": set(),  # the real-estate DW mock builder (seed scripts, tests)
    "conversations": {"core", "persistence"},
    "memory": {"core", "persistence"},
    "artifacts": {"core", "persistence", "warehouse"},
    "runtime": {"core", "config", "conversations", "memory", "plugins"},
    "http": {"core", "conversations", "artifacts", "runtime"},
    "mcp": {"core", "config", "artifacts", "warehouse", "plugins", "scopes"},
}


def _unit(path: Path) -> str:
    parts = path.relative_to(ROOT).parts
    return parts[0].removesuffix(".py") if len(parts) > 1 or parts[0] != "__init__.py" else ""


def _backend_imports(path: Path) -> list[tuple[int, str, list[str]]]:
    """`(line, module, imported names)` of every `vdagent_backend.*` import in the file."""
    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("vdagent_backend."):
            found.append((node.lineno, node.module, [a.name for a in node.names]))
        elif isinstance(node, ast.Import):
            found += [(node.lineno, a.name, []) for a in node.names if a.name.startswith("vdagent_backend.")]
    return found


def _modules() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def test_every_module_belongs_to_a_known_unit() -> None:
    units = {_unit(p) for p in _modules()} - {"", "app"}
    assert units <= set(ALLOWED), f"add these units to the dependency rule: {sorted(units - set(ALLOWED))}"


def test_units_import_only_what_the_dependency_rule_allows() -> None:
    violations: list[str] = []
    for path in _modules():
        unit = _unit(path)
        for line, module, _ in _backend_imports(path):
            target = module.split(".")[1]
            if unit in ("app", target):
                continue
            if target == "app" or target not in ALLOWED.get(unit, set()):
                violations.append(f"{path.relative_to(ROOT)}:{line}: {unit or '__init__'} imports {target}")
    assert violations == []


def test_imports_across_packages_use_only_the_package_api() -> None:
    violations: list[str] = []
    for path in _modules():
        unit = _unit(path)
        for line, module, names in _backend_imports(path):
            target = module.split(".")[1]
            if target == unit or not (ROOT / target).is_dir():
                continue
            exported = set(getattr(importlib.import_module(f"vdagent_backend.{target}"), "__all__", ()))
            if module != f"vdagent_backend.{target}" or not set(names) <= exported:
                violations.append(f"{path.relative_to(ROOT)}:{line}: from {module} import {', '.join(names)}")
    assert violations == []


def test_every_package_documents_what_it_may_import_and_declares_its_api() -> None:
    for init in sorted(ROOT.glob("*/__init__.py")):
        package = importlib.import_module(f"vdagent_backend.{init.parent.name}")
        assert package.__doc__ and "May import:" in package.__doc__, init.parent.name
        assert isinstance(getattr(package, "__all__", None), list), init.parent.name
