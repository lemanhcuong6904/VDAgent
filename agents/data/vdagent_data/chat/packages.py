"""The packages the explanation chat reads: the newest dataset Data stored for the user, with its own metric and dq.

Only the Backend's artifact tools are used (`artifact_list`, `artifact_get`): the chat never queries the warehouse and never
writes. The user's scope is already applied by the Backend, which lists the caller's artifacts only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vdagent_data.steps import Tools


@dataclass(frozen=True)
class Packages:
    dataset: dict[str, Any]
    metric: dict[str, Any] | None = None
    dq: dict[str, Any] | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return self.dataset["payload"]

    @property
    def limitations(self) -> list[str]:
        """The raw limitation codes of the three artifacts, each once."""
        envelopes = (self.dataset, self.metric, self.dq)
        return sorted({code for e in envelopes if e for code in e.get("limitations") or []})


def _newest(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return max(artifacts, key=lambda a: (a["created_at"], a["version"]))


async def _derived(tools: Tools, dataset: dict[str, Any], artifact_type: str) -> dict[str, Any] | None:
    """The newest artifact of `artifact_type` of the dataset's run that was built from exactly this dataset version."""
    listed = (await tools.call("artifact_list", {"run_id": dataset["run_id"], "artifact_type": artifact_type}))["artifacts"]
    built_from = [a for a in listed
                  if any(r["artifact_id"] == dataset["artifact_id"] and r["version"] == dataset["version"] for r in a["input_artifact_refs"])]
    if not built_from:
        return None
    chosen = _newest(built_from)
    return await tools.call("artifact_get", {"artifact_id": chosen["artifact_id"], "version": chosen["version"]})


async def load_latest(tools: Tools) -> Packages | None:
    """The newest dataset of the caller with its metric and dq, or `None` when Data has stored no dataset yet."""
    listed = (await tools.call("artifact_list", {"artifact_type": "dataset"}))["artifacts"]
    if not listed:
        return None
    newest = _newest(listed)
    dataset = await tools.call("artifact_get", {"artifact_id": newest["artifact_id"], "version": newest["version"]})
    return Packages(dataset, await _derived(tools, dataset, "metric"), await _derived(tools, dataset, "dq"))
