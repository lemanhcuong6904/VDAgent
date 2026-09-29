"""Per-step budgets (build spec 02 §2): LLM calls, SQL runs and wall-clock seconds. Exceeding one raises
`BudgetExceeded`; the pipeline turns it into `BUDGET_EXCEEDED` with whatever valid package it already has."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    def __init__(self, what: str, limit: float) -> None:
        super().__init__(f"{what} budget of {limit:g} exceeded")
        self.what = what


@dataclass
class Budget:
    llm_calls: int = 12
    sql_runs: int = 20
    seconds: float = 90.0
    used_llm: int = 0
    used_sql: int = 0
    started: float = field(default_factory=time.monotonic)

    def _check_time(self) -> None:
        if time.monotonic() - self.started > self.seconds:
            raise BudgetExceeded("time", self.seconds)

    def spend_sql(self, n: int = 1) -> None:
        self._check_time()
        if self.used_sql + n > self.sql_runs:
            raise BudgetExceeded("sql", self.sql_runs)
        self.used_sql += n

    def spend_llm(self, n: int = 1) -> None:
        self._check_time()
        if self.used_llm + n > self.llm_calls:
            raise BudgetExceeded("llm", self.llm_calls)
        self.used_llm += n

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)
