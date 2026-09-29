"""T3 guarded Text-to-SQL (build spec 02 §6): N candidates → linter → execute → consensus on the result hash.

No consensus → the selector picks one and the result is LOW_CONFIDENCE; a skeptical evaluator (seeing only the
profile, never rows) can also downgrade it. Nothing the model writes reaches the database without the linter.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from vdagent_agentkit.llm import LlmRouter
from vdagent_agentkit.mcp_client import McpSession
from vdagent_data.budgets import Budget
from vdagent_data.context import DATA_NOTE, t3_messages
from vdagent_data.pipeline.s0_intake import Intake
from vdagent_data.pipeline.s5_execute import QueryOutcome, execute
from vdagent_data.sql.compile_t1 import render
from vdagent_data.sql.validate import validate

T3_TEMPERATURE = 0.7


class SqlCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str
    rationale: str = ""


class SqlCandidates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[SqlCandidate] = Field(min_length=1, max_length=8)


class Pick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    reason: str


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    satisfies: bool
    reason: str


@dataclass
class T3Result:
    outcome: QueryOutcome | None
    low_confidence: bool
    reason: str
    lineage: dict[str, Any] = field(default_factory=dict)


def _result_hash(outcome: QueryOutcome) -> str:
    rows = sorted(json.dumps(r, ensure_ascii=False, default=str) for r in outcome.rows)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


async def run_t3(
    need: str, intake: Intake, session: McpSession, router: LlmRouter, budget: Budget, *, n: int = 4
) -> T3Result:
    messages = t3_messages(need, snapshot_id=intake.snapshot_id, config_keys=sorted(k for k, v in intake.config.items() if isinstance(v, int)))
    budget.spend_llm()
    generated = await router.structured(SqlCandidates, messages, temperature=T3_TEMPERATURE)
    budget.spend_llm(generated.calls - 1)
    rejected: list[dict[str, str]] = []
    ran: list[tuple[int, QueryOutcome]] = []
    for i, candidate in enumerate(generated.value.candidates[:n]):
        checked = validate(candidate.sql, snapshot_key=intake.snapshot_key, scope=intake.scope)
        if not checked.ok or checked.sql is None:
            rejected += [{"candidate": str(i), "code": v.code, "detail": v.detail} for v in checked.violations]
            continue
        try:
            final = render(checked.sql, intake.config)
        except (KeyError, ValueError) as exc:
            rejected.append({"candidate": str(i), "code": "UNKNOWN_THRESHOLD", "detail": str(exc)})
            continue
        budget.spend_sql()
        outcome = await execute(session, final, name=f"t3_candidate_{i}")
        if isinstance(outcome, QueryOutcome):
            ran.append((i, outcome))
        else:
            rejected.append({"candidate": str(i), "code": "SQL_ERROR", "detail": outcome.error[:200]})
    lineage: dict[str, Any] = {"tier": "T3", "candidates": min(n, len(generated.value.candidates)), "rejected": rejected}
    if not ran:
        return T3Result(None, True, "Không có truy vấn ứng viên nào hợp lệ.", lineage)

    groups: dict[str, list[tuple[int, QueryOutcome]]] = defaultdict(list)
    for i, outcome in ran:
        groups[_result_hash(outcome)].append((i, outcome))
    best = max(groups.values(), key=len)
    low_confidence, reason = False, "Đồng thuận giữa các ứng viên."
    if len(best) >= 2:
        chosen_index, chosen = best[0]
        lineage["consensus"] = len(best)
    else:
        budget.spend_llm()
        options = [{"index": i, "sql": o.sql, "profile": o.for_llm()} for i, o in ran]
        pick = await router.structured(Pick, [
            {"role": "system", "content": "Chọn truy vấn đáp ứng đúng nhu cầu nhất. " + DATA_NOTE},
            {"role": "user", "content": f"<data>\n{need}\n</data>\n" + json.dumps(options, ensure_ascii=False)},
        ])
        by_index = dict(ran)
        chosen_index = pick.value.index if pick.value.index in by_index else ran[0][0]
        chosen = by_index[chosen_index]
        low_confidence, reason = True, "Các ứng viên không đồng thuận; truy vấn được chọn cần kiểm tra."
        lineage["consensus"] = 1
    lineage["selected"] = chosen_index

    budget.spend_llm()
    verdict = await router.structured(Verdict, [
        {"role": "system", "content": "Bạn là người kiểm tra hoài nghi: kết quả có đáp ứng đúng nhu cầu không? " + DATA_NOTE},
        {"role": "user", "content": f"<data>\n{need}\n</data>\nSQL: {chosen.sql}\nHồ sơ kết quả: "
                                    + json.dumps(chosen.for_llm(), ensure_ascii=False)},
    ])
    if not verdict.value.satisfies:
        low_confidence, reason = True, f"Bộ kiểm tra nghi ngờ: {verdict.value.reason}"
    lineage.update({"sql": chosen.sql, "sql_hash": hashlib.sha256(chosen.sql.encode()).hexdigest(),
                    "dataset_id": chosen.dataset_id, "low_confidence": low_confidence})
    return T3Result(chosen, low_confidence, reason, lineage)
