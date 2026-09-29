"""UserContext and scope checks (D8, build spec 00 §2). Issued by the Backend, never by an LLM or the question."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(extra="forbid", frozen=True)


class AuthorizedScope(BaseModel):
    model_config = FROZEN

    project_ids: list[str] = Field(default_factory=list)
    zone_ids: list[str] = Field(default_factory=list)  # zone-level grants inside projects not granted whole

    def contains(self, *, project_id: str, zone_id: str | None = None) -> bool:
        """True when the whole project is granted, or the zone is."""
        return project_id in self.project_ids or (zone_id is not None and zone_id in self.zone_ids)


class UserContext(BaseModel):
    model_config = FROZEN

    user_id: str
    role: Literal["SALES_OPS", "SALES_MANAGER", "PROJECT_DIRECTOR", "DATA_ANALYST"] = "SALES_OPS"
    authorized_scope: AuthorizedScope = Field(default_factory=AuthorizedScope)
