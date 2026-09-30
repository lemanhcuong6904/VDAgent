"""This agent's brain. EDIT THIS FILE (and add any modules it needs).

Implement `vdagent_sdk.Agent` (`invoke` and `compact`; the package docstring describes the types and
the turn requirements) with any framework, and register it from `setup()` in `__init__.py`.

This stub echoes the inbound message and keeps a naive summary; it needs no LLM.
"""

from __future__ import annotations

from vdagent_sdk import InvocationContext, Message

DESCRIPTION = "Echoes the inbound message."
SUMMARY_MAX_CHARS = 2000


class EchoAgent:
    async def invoke(self, ctx: InvocationContext) -> None:
        await ctx.emit_assistant(f"echo: {ctx.history[-1]['content']}")

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        lines = [previous_summary] if previous_summary else []
        lines += [m["content"] for m in messages if m["role"] == "user"]
        return "\n".join(lines)[-SUMMARY_MAX_CHARS:]
