"""Where Compare finds its inputs: the hero fixture ships with the plugin, the CSV pack does not."""
from __future__ import annotations

from pathlib import Path

import pytest

from vdagent_compare.vh_data import default_data_root, load_hero_package
from vdagent_compare.vh_service import CompareService


def _make_pack(root: Path) -> Path:
    (root / "export").mkdir(parents=True)
    (root / "export" / "snapshot_manifest.csv").write_text("snapshot_id\n", encoding="utf-8")
    return root


def test_hero_fixture_ships_with_the_plugin():
    package = load_hero_package()
    assert package.name == "hero_fixture"
    assert any(unit.unit_code == "A12-08" for unit in package.units)


def test_env_var_wins_over_repo_locations(tmp_path, monkeypatch):
    chosen = _make_pack(tmp_path / "elsewhere")
    _make_pack(tmp_path / "repo" / "warehouse" / "vhop")
    monkeypatch.setenv("VDAGENT_VHOP_DATA_DIR", str(chosen))
    assert default_data_root(repo_root=tmp_path / "repo") == chosen.resolve()


@pytest.mark.parametrize("first", ["warehouse/vhop", "var/vhop", "data/vhop"])
def test_repo_locations_are_tried_in_order(tmp_path, monkeypatch, first):
    monkeypatch.delenv("VDAGENT_VHOP_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    order = ["warehouse/vhop", "var/vhop", "data/vhop"]
    for location in order[order.index(first):]:
        _make_pack(tmp_path / "repo" / location)
    assert default_data_root(repo_root=tmp_path / "repo") == (tmp_path / "repo" / first).resolve()


def test_missing_pack_names_every_location_tried(tmp_path, monkeypatch):
    monkeypatch.delenv("VDAGENT_VHOP_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="warehouse/vhop"):
        default_data_root(repo_root=tmp_path / "repo")


def test_hero_questions_work_without_the_csv_pack(tmp_path):
    service = CompareService(root=tmp_path / "no-pack-here")
    result = service.run({"subject": {"entityType": "unit", "entityCode": "A12-08"}})
    assert result["comparison"]["status"] == "VALID"
    assert result["peer_definition"]["peerCount"] == 5
