"""vdagent plugin interface. Plugins import only this package, never `vdagent_backend`.

A plugin is an importable Python module listed in the Backend's `config.yaml`:

    plugins:
      - module: vdagent_data
        opts: {}            # free-form; handed to setup() as a dict, never interpreted by the Backend

The module MUST export

    def setup(api: PluginAPI, opts: Mapping[str, Any]) -> None | Awaitable[None]

The Backend calls it once at startup, in list order, and awaits it if it returns an awaitable.
Through `api` the plugin registers its agents and shutdown hooks. If `setup` raises, nothing it
registered is kept: the plugin is logged as failed and skipped, and the Backend still starts.
Raise `PluginConfigError` for bad or missing configuration (logged without a traceback).

The Backend then runs each registered agent's turns by awaiting `agent.invoke(ctx)` in its own
event loop. A turn follows these rules. Rules marked (Backend) are checked by `ctx`: breaking one
raises `ContractViolation` at the offending call and fails the turn, even if the plugin catches it.

- R1  No hidden memory between turns: `ctx.summary`, `ctx.history` and `ctx.memory` are the whole
      truth. Keep state that spans turns in `ctx.memory`, never on `self` or elsewhere.
- R2  (Backend) Emit an assistant step (with its tool calls) before any result or `call_agent` for
      those calls. A new assistant step may only be emitted once every tool call of the previous
      one has a result. Tool-call ids are non-empty and unique within a step.
- R3  (Backend) Every tool call gets exactly one `emit_tool_result`, including `send_to_agent`:
      `call_agent`, then emit the reply as its result.
- R4  (Backend) `call_agent` only for an unresolved `send_to_agent` call of the latest assistant
      step, at most once per id; no `emit_tool_result` for that id while its call is pending.
- R5  (Backend) The turn ends when `invoke` returns. By then every tool call is resolved and the
      last emitted assistant step has no tool calls; its content is the final answer. Nothing may
      be emitted after `invoke` returns.
- R6  Tool failures become result content `error: …` and the turn continues. Model timeout →
      raise `AgentTimeoutError`. Any other exception fails the turn.
- R7  Emit at most `ctx.max_steps` assistant steps. Internal model calls (embeddings, extraction,
      judges, classifiers) are the plugin's own budget.
- R8  One agent object serves concurrent turns: keep per-turn state off `self`.
- R9  Never swallow `asyncio.CancelledError`; a cancelled task arrives as cancellation.
- R10 Never block the event loop: it is the Backend's. Run blocking I/O or CPU-heavy work through
      `asyncio.to_thread` or an executor.
- R11 Never write to `os.environ` or other process-global state shared with other plugins. Read
      your own `.env` with `dotenv.dotenv_values()`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "SEND_TO_AGENT",
    "Agent",
    "AgentTimeoutError",
    "ContractViolation",
    "InvocationContext",
    "McpEndpoint",
    "Memory",
    "Message",
    "Note",
    "Peer",
    "PluginAPI",
    "PluginConfigError",
    "ToolCall",
]

SEND_TO_AGENT = "send_to_agent"
"""The Backend only accepts `call_agent` for a tool call with exactly this name."""

Message = dict[str, Any]
"""One history message in OpenAI chat-completions shape:

- `{"role": "user", "content": str}` — inbound, rendered as `[from: <sender>] <text>`
- `{"role": "assistant", "content": str | None, "tool_calls": [{"id": str, "type": "function",
  "function": {"name": str, "arguments": str}}]}` — `tool_calls` present only when non-empty;
  `content` is `None` when empty and tool calls are present
- `{"role": "tool", "tool_call_id": str, "content": str}`
"""


@dataclass(frozen=True)
class ToolCall:
    """A tool call requested by an assistant step. `arguments_json` is the raw JSON object text."""

    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class Peer:
    """Another registered agent this one may call through `send_to_agent`."""

    name: str
    description: str


@dataclass(frozen=True)
class McpEndpoint:
    """The Backend's MCP server for this turn.

    Connect over streamable HTTP with header `Authorization: Bearer <token>`. The token is valid
    only while the turn runs; the Backend decides which tools this agent sees.
    """

    url: str
    token: str


@dataclass(frozen=True)
class Note:
    """One memory note of a (user, agent) scope."""

    id: int
    kind: str
    text: str
    created_at: str
    score: float | None = None
    """Vector search: cosine distance (lower is closer). Keyword search: bm25 (lower is better). Else None."""


class Memory(Protocol):
    """Notes of one (user, agent) scope, kept by the Backend across turns and tasks.

    The Backend only stores and ranks notes; what to save, when, and what reaches the model is the
    plugin's decision. Embeddings are computed by the plugin (any model, any dimension).
    """

    async def save(self, text: str, kind: str = "note", embedding: Sequence[float] | None = None) -> int:
        """Store a note; returns its id. `ValueError` for empty `text`/`kind` or an empty embedding."""
        ...

    async def search(self, query: str, limit: int = 5, embedding: Sequence[float] | None = None) -> list[Note]:
        """With `embedding`: nearest notes by cosine distance among this scope's notes whose embedding
        has the same dimension. Without: FTS5 keyword match on `query`. Best first."""
        ...

    async def recent(self, limit: int = 10) -> list[Note]:
        """Newest first."""
        ...

    async def delete(self, note_id: int) -> bool:
        """False if the note does not exist or belongs to another scope."""
        ...


class InvocationContext(Protocol):
    """Everything one turn knows, plus the only ways to report progress. Built by the Backend."""

    invocation_id: str
    task_id: str
    user_id: str
    summary: str
    """Rolling summary of this user's earlier, compacted tasks; `""` if none."""
    history: list[Message]
    """Uncompacted messages in order; the last one is the inbound message that started the turn."""
    peers: list[Peer]
    """Every other registered agent."""
    mcp: McpEndpoint
    max_steps: int
    """Budget of assistant steps for this turn (R7)."""

    @property
    def memory(self) -> Memory:
        """This user's notes for the invoked agent (R1). The plugin cannot choose another scope."""
        ...

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        """Record one assistant step. A step without tool calls that ends the turn is the answer."""
        ...

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        """Record the result of one tool call of the latest assistant step."""
        ...

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        """Send `message` to agent `target` for `send_to_agent` call `tool_call_id`; wait for its reply.

        Returns the peer's reply text, or `error: …` text when the Backend rejects the call or the
        peer fails. The reply is not recorded automatically: emit it with `emit_tool_result`.
        """
        ...


class Agent(Protocol):
    """What a plugin registers. One instance serves every turn (R8)."""

    async def invoke(self, ctx: InvocationContext) -> None:
        """Run one turn, reporting every step through `ctx` (R2–R5)."""
        ...

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        """Fold `messages` from finished tasks into `previous_summary`; return the new summary."""
        ...


class PluginAPI(Protocol):
    """The handle `setup()` receives. Valid only while `setup` runs."""

    plugin: str
    """The module name from `config.yaml`."""
    log: logging.Logger
    """Logger `vdagent.plugin.<module>`."""

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        """Offer `agent` under `name`. Raises `ValueError` for an empty name or description, or a
        name already registered (by this plugin or an earlier one)."""
        ...

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        """Run `fn` when the Backend stops (reverse registration order, 5 s each)."""
        ...


class PluginConfigError(Exception):
    """Raise from `setup()` for bad or missing configuration; the plugin is skipped with this message."""


class AgentTimeoutError(Exception):
    """Raise from `invoke`/`compact` when the model call times out; reported as DEADLINE_EXCEEDED."""


class ContractViolation(Exception):
    """Raised by the Backend's `ctx` when a turn breaks rules R2–R5; the turn fails."""
