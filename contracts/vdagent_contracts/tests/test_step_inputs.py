"""WS3: resolving a StepSpec's canonical Data inputs from the Artifact Store (shared by Insight and Compare)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from vdagent_contracts.errors import ErrorClass
from vdagent_contracts.messages import StepSpec
from vdagent_contracts.step_inputs import INPUT_ERROR_CLASSES, InputError, resolve_analysis_inputs, resolve_data_inputs

ALICE = "u_000000000001"
H = {"dataset": "a" * 64, "metric": "b" * 64, "dq": "c" * 64, "comparison": "d" * 64}


def _env(kind: str, **over: Any) -> dict[str, Any]:
    env: dict[str, Any] = {
        "artifact_id": f"art_{kind}", "version": 1, "artifact_type": kind, "schema_version": f"re_{kind}@1",
        "status": "VALID", "content_hash": H[kind], "snapshot_refs": ["SNAP-2026-09-28"], "semantic_config_version": "sc-1",
        "input_artifact_refs": [] if kind == "dataset" else [
            {"artifact_id": "art_dataset", "version": 1, "artifact_type": "dataset", "content_hash": H["dataset"]}],
        "limitations": [], "payload": {"tables": {"dim_unit_master": [{"unit_key": "U-PRJ-X-A12-08", "project_key": "PRJ-X"}]}}
        if kind == "dataset" else {},
    }
    env.update(over)
    return env


class FakeTools:
    def __init__(self, envs: dict[str, dict[str, Any]], scope: list[str] | None = None, user: str = ALICE) -> None:
        self.envs, self.scope, self.user = envs, scope if scope is not None else ["PRJ-X"], user

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "get_user_context":
            return {"user_id": self.user, "authorized_scope": {"project_ids": self.scope, "zone_ids": []}}
        assert name == "artifact_get"
        env = self.envs.get(args["artifact_id"])
        if env is None or env["version"] != args.get("version", env["version"]):
            raise LookupError("error: artifact not found")
        return copy.deepcopy(env)


def _envs(**over: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"art_{k}": _env(k, **over.get(k, {})) for k in ("dataset", "metric", "dq")}


def _step(refs: list[dict[str, Any]] | None = None, **over: Any) -> StepSpec:
    fields: dict[str, Any] = {
        "run_id": "t_1", "plan_id": "pl", "step_id": "B2", "idempotency_key": "pl:B2", "operation": "explain_unit",
        "user_context": {"user_id": ALICE, "authorized_scope": {"project_ids": ["PRJ-X"]}},
        "snapshot_id": "SNAP-2026-09-28", "semantic_config_version": "sc-1", "original_question": "q",
        "input_refs": refs if refs is not None else [
            {"artifact_id": f"art_{k}", "version": 1, "artifact_type": k, "content_hash": H[k]} for k in ("dataset", "metric", "dq")],
    }
    fields.update(over)
    return StepSpec.model_validate(fields)


def _analysis_step(refs: list[dict[str, Any]], **over: Any) -> StepSpec:
    fields = _step(refs, step_id="B4", idempotency_key="pl:B4", operation="draw_chart").model_dump(mode="json")
    fields.update(over)
    return StepSpec.model_validate(fields)


async def test_resolves_the_three_pinned_inputs() -> None:
    inputs = await resolve_data_inputs(_step(), FakeTools(_envs()))
    assert (inputs.dataset["artifact_id"], inputs.metric["artifact_id"], inputs.dq["artifact_id"]) == ("art_dataset", "art_metric", "art_dq")
    assert [r.artifact_id for r in inputs.refs] == ["art_dataset", "art_metric", "art_dq"]
    assert all(r.content_hash for r in inputs.refs)
    assert inputs.authorized_project_ids == ["PRJ-X"]


def _code(exc: pytest.ExceptionInfo[InputError]) -> str:
    return exc.value.code


@pytest.mark.parametrize(
    ("step_over", "env_over", "code", "klass"),
    [
        ({"snapshot_id": None}, {}, "SNAPSHOT_REQUIRED", ErrorClass.SPEC_ISSUE),
        ({"semantic_config_version": None}, {}, "SEMANTIC_VERSION_REQUIRED", ErrorClass.SPEC_ISSUE),
        ({"snapshot_id": "SNAP-2026-08-31"}, {}, "SNAPSHOT_MISMATCH", ErrorClass.SPEC_ISSUE),
        ({"semantic_config_version": "3.1.0"}, {}, "SEMANTIC_VERSION_MISMATCH", ErrorClass.SPEC_ISSUE),
        ({}, {"dataset": {"schema_version": "data_package@1"}}, "INPUT_SCHEMA_UNSUPPORTED", ErrorClass.SPEC_ISSUE),
        ({}, {"dq": {"status": "INVALID"}}, "INPUT_INVALID", ErrorClass.DATA_QUALITY),
        ({}, {"metric": {"input_artifact_refs": [{"artifact_id": "art_other", "version": 1, "artifact_type": "dataset"}]}},
         "LINEAGE_MISMATCH", ErrorClass.WRONG_RESULT),
        ({"user_context": {"user_id": "u_000000000002", "authorized_scope": {}}}, {}, "USER_CONTEXT_MISMATCH", ErrorClass.NO_ACCESS),
    ],
)
async def test_rejections(step_over: dict[str, Any], env_over: dict[str, Any], code: str, klass: ErrorClass) -> None:
    with pytest.raises(InputError) as exc:
        await resolve_data_inputs(_step(**step_over), FakeTools(_envs(**env_over)))
    assert _code(exc) == code and INPUT_ERROR_CLASSES[code] is klass


async def test_missing_type_hash_or_unknown_ref_is_rejected() -> None:
    refs = [{"artifact_id": "art_dataset", "version": 1, "artifact_type": "dataset", "content_hash": H["dataset"]}]
    with pytest.raises(InputError) as exc:
        await resolve_data_inputs(_step(refs), FakeTools(_envs()))
    assert _code(exc) == "MISSING_INPUT"

    unpinned = [{"artifact_id": f"art_{k}", "version": 1, "artifact_type": k} for k in ("dataset", "metric", "dq")]
    with pytest.raises(InputError) as exc:
        await resolve_data_inputs(_step(unpinned), FakeTools(_envs()))
    assert _code(exc) == "INPUT_HASH_REQUIRED"

    wrong = [{"artifact_id": f"art_{k}", "version": 1, "artifact_type": k, "content_hash": "0" * 64} for k in ("dataset", "metric", "dq")]
    with pytest.raises(InputError) as exc:
        await resolve_data_inputs(_step(wrong), FakeTools(_envs()))
    assert _code(exc) == "INPUT_HASH_MISMATCH" and INPUT_ERROR_CLASSES["INPUT_HASH_MISMATCH"] is ErrorClass.WRONG_RESULT

    gone = [{"artifact_id": "art_gone", "version": 1, "artifact_type": "dataset", "content_hash": H["dataset"]},
            *_step().model_dump(mode="json")["input_refs"][1:]]
    with pytest.raises(InputError) as exc:
        await resolve_data_inputs(_step(gone), FakeTools(_envs()))
    assert _code(exc) == "INPUT_NOT_FOUND" and INPUT_ERROR_CLASSES["INPUT_NOT_FOUND"] is ErrorClass.NO_DATA


async def test_dataset_rows_outside_the_callers_scope_are_rejected() -> None:
    envs = _envs(dataset={"payload": {"tables": {"dim_unit_master": [{"unit_key": "U-PRJ-Y-D12-09", "project_key": "PRJ-Y"}]}}})
    with pytest.raises(InputError) as exc:
        await resolve_data_inputs(_step(), FakeTools(envs))
    assert _code(exc) == "SCOPE_VIOLATION" and INPUT_ERROR_CLASSES["SCOPE_VIOLATION"] is ErrorClass.NO_ACCESS


async def test_analysis_inputs_accept_an_explicit_dataset_ref() -> None:
    dataset = _env("dataset")
    dataset_ref = {"artifact_id": "art_dataset", "version": 1, "artifact_type": "dataset", "content_hash": H["dataset"]}
    comparison = {
        "artifact_id": "art_comparison", "version": 1, "artifact_type": "comparison", "schema_version": "comparison@1",
        "status": "VALID", "content_hash": H["comparison"], "snapshot_refs": ["SNAP-2026-09-28"],
        "semantic_config_version": "sc-1", "input_artifact_refs": [dataset_ref], "limitations": [], "payload": {},
    }
    refs = [dataset_ref, {"artifact_id": "art_comparison", "version": 1, "artifact_type": "comparison", "content_hash": H["comparison"]}]

    inputs = await resolve_analysis_inputs(_analysis_step(refs), FakeTools({"art_dataset": dataset, "art_comparison": comparison}))

    assert inputs.dataset_ref.artifact_id == "art_dataset"
    assert {k.value for k in inputs.refs} >= {"dataset", "comparison"}


async def test_analysis_inputs_reject_dataset_ref_that_disagrees_with_upstream_lineage() -> None:
    dataset = _env("dataset")
    other_hash = "e" * 64
    other_dataset = _env("dataset", artifact_id="art_other_dataset", content_hash=other_hash)
    dataset_ref = {"artifact_id": "art_dataset", "version": 1, "artifact_type": "dataset", "content_hash": H["dataset"]}
    other_ref = {"artifact_id": "art_other_dataset", "version": 1, "artifact_type": "dataset", "content_hash": other_hash}
    comparison = {
        "artifact_id": "art_comparison", "version": 1, "artifact_type": "comparison", "schema_version": "comparison@1",
        "status": "VALID", "content_hash": H["comparison"], "snapshot_refs": ["SNAP-2026-09-28"],
        "semantic_config_version": "sc-1", "input_artifact_refs": [other_ref], "limitations": [], "payload": {},
    }
    refs = [dataset_ref, {"artifact_id": "art_comparison", "version": 1, "artifact_type": "comparison", "content_hash": H["comparison"]}]

    with pytest.raises(InputError) as exc:
        await resolve_analysis_inputs(_analysis_step(refs), FakeTools({
            "art_dataset": dataset, "art_other_dataset": other_dataset, "art_comparison": comparison,
        }))
    assert _code(exc) == "LINEAGE_MISMATCH"
