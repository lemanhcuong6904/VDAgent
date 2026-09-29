from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from vdagent_contracts.envelope import ArtifactEnvelope, ArtifactRef, ArtifactStatus, ArtifactType, Producer
from vdagent_contracts.status import to_envelope_status


def _envelope(**overrides: Any) -> ArtifactEnvelope:
    fields: dict[str, Any] = {
        "artifact_id": "art_1",
        "run_id": "t_1",
        "task_id": "t_1",
        "user_id": "u_000000000001",
        "artifact_type": "data_package",
        "schema_version": "data_package@1",
        "version": 1,
        "status": "VALID",
        "producer": {"agent": "data", "agent_version": "0.1.0", "prompt_version": None, "model_id": None},
        "snapshot_refs": ["SNAP-2026-09-28"],
        "semantic_config_version": "sc-1",
        "payload": {"rows": 3, "median": Decimal("64500000")},
    }
    fields.update(overrides)
    return ArtifactEnvelope.model_validate(fields)


def test_envelope_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _envelope(unexpected="x")


def test_envelope_is_frozen() -> None:
    envelope = _envelope()
    with pytest.raises(ValidationError):
        envelope.status = ArtifactStatus.INVALID  # type: ignore[misc]


def test_artifact_type_enum_matches_sp_6_2() -> None:
    assert {t.value for t in ArtifactType} == {
        "data_package", "metric", "dq", "dataset", "market_context", "peer_definition",
        "comparison", "insight", "chart_spec", "report", "run_summary", "run_state",
    }


def test_status_map_data_validated_is_valid() -> None:
    assert to_envelope_status("VALIDATED") is ArtifactStatus.VALID
    assert to_envelope_status("VALID") is ArtifactStatus.VALID
    with pytest.raises(ValueError):
        to_envelope_status("OK")


def test_status_map_chart_validated_partial_failed() -> None:
    assert to_envelope_status("validated") is ArtifactStatus.VALID
    assert to_envelope_status("partial") is ArtifactStatus.PARTIAL
    assert to_envelope_status("failed") is ArtifactStatus.INVALID


def test_partial_requires_limitations() -> None:
    with pytest.raises(ValidationError):
        _envelope(status="PARTIAL", limitations=[])
    assert _envelope(status="PARTIAL", limitations=["SMALL_SAMPLE"]).status is ArtifactStatus.PARTIAL


def test_content_hash_ignores_identity_and_owner() -> None:
    first = _envelope()
    second = _envelope(artifact_id="art_2", run_id="t_2", task_id="t_2", version=3, user_id="u_000000000002")
    assert first.compute_content_hash() == second.compute_content_hash()
    assert first.compute_content_hash() != _envelope(payload={"rows": 4}).compute_content_hash()


def test_artifact_ref_roundtrip() -> None:
    ref = ArtifactRef(artifact_id="art_1", version=2, artifact_type=ArtifactType.INSIGHT)
    assert ArtifactRef.model_validate(ref.model_dump(mode="json")) == ref
    assert Producer(agent="data", agent_version="0.1.0").label == "data@0.1.0"
