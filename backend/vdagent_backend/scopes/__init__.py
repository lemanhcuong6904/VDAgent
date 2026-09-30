"""User scopes (D8): the authorized projects / zones of each user — the only source of `user_context` for agents.

A row grants a whole project (`zone_id` NULL) or one zone of it; an unknown user has an empty scope. The demo grants
(Alice → PRJ-X, Bob → PRJ-Y) are seeded only for demo users that have no scope at all (B-10), never widened.

May import: `core`, `persistence`.
"""

from vdagent_backend.scopes.scopes import DEMO_SCOPES, UserScopes, seed_demo_scopes, seed_missing_demo_scopes

__all__ = ["DEMO_SCOPES", "UserScopes", "seed_demo_scopes", "seed_missing_demo_scopes"]
