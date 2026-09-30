"""`needs_pack` tests run only where the DATA team's VHOP CSV pack is available."""
from __future__ import annotations

import pytest

from vdagent_compare.vh_data import default_data_root


def _pack_available() -> bool:
    try:
        default_data_root()
    except FileNotFoundError:
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "needs_pack: uses the VHOP CSV pack (skipped when it is absent)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _pack_available():
        return
    skip = pytest.mark.skip(reason="VHOP CSV pack not found; see agents/compare/README.md")
    for item in items:
        if "needs_pack" in item.keywords:
            item.add_marker(skip)
