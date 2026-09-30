"""WS3 cross-agent consistency: Insight and Compare read the SAME Data artifacts and keep one snapshot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vdagent_compare.stepspec import run_step as run_compare
from vdagent_compare.tests.test_dw_integration import compare_step, data_refs
from vdagent_data.tests.conftest import McpPort, alice, mcp_tools, re_db  # noqa: F401  (pytest fixtures)
from vdagent_insight.settings import CONFIG_DIR, SemanticConfigRegistry, load_llm_config
from vdagent_insight.stepspec import StepEnv
from vdagent_insight.stepspec import run_step as run_insight
from vdagent_insight.store import InsightStore
from vdagent_insight.tests.test_dw_integration import insight_step


def _text(value: Any) -> str:
    return str(value)


async def test_both_agents_consume_the_same_dataset(alice: McpPort, tmp_path: Path) -> None:
    refs = await data_refs(alice)
    env = StepEnv(registry=SemanticConfigRegistry(CONFIG_DIR), llm=load_llm_config(CONFIG_DIR / "llm.yaml"),
                  store=InsightStore(tmp_path / "insight.db"))
    insight_report = await run_insight(insight_step(refs), alice.as_agent("insight"), env)
    compare_report = await run_compare(compare_step(refs), alice.as_agent("compare"))
    assert insight_report.state == compare_report.state == "completed"

    outs = [await alice.call("artifact_get", {"artifact_id": r.artifact_id, "version": r.version})
            for r in [*insight_report.artifact_refs, *compare_report.artifact_refs]]
    assert {o["artifact_type"] for o in outs} == {"insight", "peer_definition", "comparison"}
    for out in outs:
        assert out["input_artifact_refs"][0] == refs[0]  # the one dataset, same version and hash
        assert out["snapshot_refs"] == ["SNAP-2026-09-28"] and out["semantic_config_version"] == "sc-1"
        assert "PRJ-Y" not in _text(out["payload"]) and "D12-09" not in _text(out["payload"])
    assert insight_report.snapshot_id == compare_report.snapshot_id == "SNAP-2026-09-28"
