"""The interface between an agent plugin and the vdagent Backend.

A plugin imports only this package, never `vdagent_backend`. This page is the whole contract: how
the Backend loads your plugin, what a turn receives and must report, what the Backend does around
it, and how to fix the usual failures.

## Start here

1. Copy `agents/_template` to `agents/<name>` and rename `agent_template/` to `vdagent_<name>/`.
2. Write your `Agent` (`invoke` and `compact`) in `vdagent_<name>/agent.py`; start from
   [Write a turn](#write-a-turn).
3. Register it in `setup()` in `vdagent_<name>/__init__.py`:
   `api.register_agent(name="<name>", description="…", agent=MyAgent(...))`. Other agents read the
   description when they decide whom to call: say what you do and what you return.
4. Wire it into the Backend: add `agents/<name>` to the uv workspace in the root `pyproject.toml`,
   list `- module: vdagent_<name>` under `plugins:` in `backend/config.yaml`, and grant MCP tools
   to `<name>` in `PERMISSIONS` in `backend/vdagent_backend/mcp/tools.py`. The template's README
   lists every file, including the Docker ones.
5. Run `uv run pytest agents/<name>`, then `make backend`. The log shows
   `plugin vdagent_<name> loaded: <name>`, or `plugin vdagent_<name> failed: <reason>`.

## The plugin module

The Backend loads the modules listed in `backend/config.yaml`:

```yaml
plugins:
  - module: vdagent_data
    opts: {}          # optional, free-form: passed to setup() as a dict
    enabled: true     # optional: false skips the plugin
```

Each module exports `setup(api: PluginAPI, opts: Mapping[str, Any]) -> None` (or `async def`):

- The Backend calls it once at startup, in list order, before any turn runs.
- Read your settings here, build your clients, and register your agents with
  `api.register_agent(...)`.
- For a missing or bad setting, raise `PluginConfigError("…")`: the Backend logs
  `plugin <module> failed: <message>` and starts without your agent. Any other exception does the
  same, with a traceback in the log.
- If `setup` raises, nothing it registered is kept.

## Write a turn

For every message your agent receives, the Backend calls `await agent.invoke(ctx)`. Report each
model step through `ctx`: the Backend stores it, shows it in the UI and puts it into later history.
A turn always follows this order:

1. `ctx.emit_assistant(content, tool_calls)`: the model's step, before any of its tool calls run.
2. `ctx.emit_tool_result(id, text)` once per tool call. For a `send_to_agent` call, first get the
   text with `ctx.call_agent(id, target, message)`.
3. Repeat 1–2 until the model answers, then `ctx.emit_assistant(answer)` without tool calls and
   return. That content is the answer your caller receives.

A complete agent. `model` stands for your LLM client, built in `setup()`:
`await model.complete(messages, tools)` returns `(content, tool_calls)` with `tool_calls` a list of
`ToolCall`, and `await model.summarise(previous_summary, messages)` returns a string.

```python
import asyncio
import json

from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from vdagent_sdk import SEND_TO_AGENT, AgentTimeoutError, InvocationContext, Message, ToolCall

TOOL_TIMEOUT_S = 30
MAX_RESULT_CHARS = 16_000


class MyAgent:
    def __init__(self, model) -> None:
        self._model = model  # shared by every turn: keep per-turn state in local variables

    async def invoke(self, ctx: InvocationContext) -> None:
        messages = [{"role": "system", "content": f"You are … Earlier work:\\n{ctx.summary}"}, *ctx.history]
        headers = {"Authorization": f"Bearer {ctx.mcp.token}"}
        async with create_mcp_http_client(headers=headers) as http:
            async with Client(streamable_http_client(ctx.mcp.url, http_client=http), cache=None) as mcp:
                tools = [*mcp_tool_schemas(await mcp.list_tools()), send_to_agent_schema(ctx.peers)]
                for step in range(1, ctx.max_steps + 1):
                    last = step == ctx.max_steps  # last step: no tools, so the model must answer
                    try:
                        content, calls = await self._model.complete(messages, [] if last else tools)
                    except TimeoutError as e:
                        raise AgentTimeoutError(str(e)) from e
                    calls = [] if last else calls
                    await ctx.emit_assistant(content, calls)  # 1. the step, before its results
                    messages.append(assistant_message(content, calls))
                    if not calls:
                        return  # 3. a step without tool calls is the answer
                    results = await asyncio.gather(*(run_tool(ctx, mcp, c) for c in calls))
                    for call, text in zip(calls, results):
                        await ctx.emit_tool_result(call.id, text)  # 2. one result per call
                        messages.append({"role": "tool", "tool_call_id": call.id, "content": text})

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        return await self._model.summarise(previous_summary, messages)


async def run_tool(ctx: InvocationContext, mcp: Client, call: ToolCall) -> str:
    try:
        args = json.loads(call.arguments_json)
        if call.name == SEND_TO_AGENT:
            return await ctx.call_agent(call.id, args["agent"], args["message"])
        result = await asyncio.wait_for(mcp.call_tool(call.name, args), TOOL_TIMEOUT_S)
        return result.content[0].text[:MAX_RESULT_CHARS]  # MCP errors arrive as "error: …" text
    except Exception as e:  # a failed tool is a result the model can react to, not a crash
        return f"error: {e}"


def mcp_tool_schemas(listed) -> list[dict]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema}}
        for t in listed.tools
    ]


def send_to_agent_schema(peers) -> dict:
    roster = "\\n".join(f"- {p.name}: {p.description}" for p in peers)
    parameters = {
        "type": "object",
        "properties": {"agent": {"type": "string", "enum": [p.name for p in peers]}, "message": {"type": "string"}},
        "required": ["agent", "message"],
    }
    description = f"Send a message to another agent and wait for its answer. Agents:\\n{roster}"
    return {"type": "function", "function": {"name": SEND_TO_AGENT, "description": description, "parameters": parameters}}


def assistant_message(content: str, calls: list[ToolCall]) -> Message:
    if not calls:
        return {"role": "assistant", "content": content}
    tool_calls = [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments_json}} for c in calls]
    return {"role": "assistant", "content": content or None, "tool_calls": tool_calls}
```

The same loop works with any framework (LangChain, LangGraph, the OpenAI Agents SDK): emit from the
hook that sees each model response and each tool result. `agents/insight` and `agents/report` are
working examples.

## Requirements the Backend checks

Break one of these and the offending `ctx` call raises `ContractViolation`. The turn fails with
`contract violation: <message>` even if you catch the exception, the UI shows the failure, and your
caller receives `error: <agent> failed: contract violation: <message>`.

### Record the step before its results

- **Do:** call `emit_assistant(content, tool_calls)` before any `emit_tool_result` or `call_agent`
  for those calls. Start the next step only after every call of this step has a result. Give each
  tool call a non-empty id that is unique within its step (the id your model returned).
- **If broken:**
  - `emit_assistant: tool calls [<ids>] of the previous step have no result yet`
  - `emit_assistant: tool-call ids must be non-empty and unique, got [<ids>]`

### Give every tool call exactly one result

- **Do:** call `emit_tool_result(id, text)` once for each tool call of the latest step, including
  `send_to_agent` calls.
- **If broken:** `emit_tool_result('<id>'): not an unresolved tool call of the latest assistant step`
  (an unknown id, an id from an older step, or a second result for the same id).

### Call other agents only through `send_to_agent`

- **Do:** call `call_agent(id, target, message)` only for a tool call named `send_to_agent` in the
  latest step, once per id, and emit its reply with `emit_tool_result(id, reply)` after it returns.
- **If broken:**
  - `call_agent('<id>'): not a tool call of the latest assistant step`
  - `call_agent('<id>'): tool call is '<name>', not send_to_agent`
  - `call_agent('<id>'): tool call already has a result`
  - `call_agent('<id>'): already called once`
  - `emit_tool_result('<id>'): its call_agent is still waiting for the reply`

### End with an answer

- **Do:** before `invoke` returns, give every tool call a result and emit a last step without tool
  calls; its content is your answer. Do not use `ctx` after returning, from a background task or a
  kept reference.
- **If broken:**
  - `invoke returned with unresolved tool calls [<ids>]`
  - `invoke returned without a final assistant step (one without tool calls)`: also when your last
    step still had tool calls, for example when your loop ran out of steps.
  - `<method>: the turn is over`: a `ctx` call after the turn ended.

## Requirements you must follow

Nothing checks these, so a mistake shows up as wrong behaviour rather than an error.

### Keep state only in `ctx`

- **Do:** treat `ctx.summary`, `ctx.history` and `ctx.memory` as everything you know about the
  user. Save what must outlive the turn with `ctx.memory.save(...)`.
- **If broken:** state kept elsewhere leaks between users, is lost on restart, and differs from
  what the UI shows.

### Keep per-turn state off `self`

- **Do:** create message lists, clients and counters inside `invoke`. One agent object serves every
  turn, and turns of different users run at the same time.
- **If broken:** concurrent turns overwrite each other's state.

### Report tool failures as results

- **Do:** catch every tool failure (MCP error, local tool error, bad arguments, unknown tool) and
  emit `error: <reason>` as its result, so the model can react. When the model call times out,
  raise `AgentTimeoutError`.
- **If broken:** any other exception fails the turn with `INTERNAL: <ExceptionType>: <message>`.
  `AgentTimeoutError` fails it with `DEADLINE_EXCEEDED: <message>`.

### Stay within `ctx.max_steps`

- **Do:** emit at most `ctx.max_steps` assistant steps (12 unless the Backend sets
  `VDAGENT_MAX_STEPS`). On the last one, give the model no tools so it has to answer. Embedding,
  extraction and judge calls do not count as steps.
- **If broken:** nothing stops you, but the user waits, and this agent's other work for the same
  user stays queued behind the turn.

### Let cancellation through

- **Do:** never swallow `asyncio.CancelledError`. `except Exception` is fine (it does not catch
  cancellation); a bare `except:` or `except BaseException` must re-raise.
- **If broken:** cancelling the task cannot stop your turn. The Backend gives up after 5 s and logs
  `invoke ignored cancellation; abandoning it`, while your code keeps running.

### Do not block the event loop

- **Do:** use async clients, and run blocking I/O or heavy computation with
  `await asyncio.to_thread(...)`.
- **If broken:** every agent, the API and the UI freeze while you block: they share one process and
  one event loop.

### Do not change process-wide state

- **Do:** read your settings with `dotenv.dotenv_values("agents/<name>/.env")` and pass them to your
  agent. Never write `os.environ`, the global logging setup or other shared state.
- **If broken:** you change the settings of every other plugin in the process.

## What happens around your turn

### What `ctx.history` holds

- Every message between this user and your agent that is not yet folded into `ctx.summary`:
  earlier turns of the current task, turns of this user's other running tasks, and finished tasks
  whose compaction failed.
- The messages use the OpenAI chat-completions shape (see `Message`); the last one is the message
  that started this turn.
- Incoming messages read `[from: <sender>] <text>`, where `<sender>` is `user` (the person in the UI)
  or the name of the agent that called you.
- After a failed turn the Backend adds `error: turn aborted (<reason>)` as the result of every
  unanswered tool call and an assistant message `[turn failed: <reason>]`. Your model sees them in
  later turns.

### One turn at a time per user

Your agent runs one turn per user at a time. Further messages from that user, or from agents
working for that user, wait in a first-in, first-out queue. Turns of different users run at the
same time on the same agent object. A `call_agent` may therefore wait while the peer finishes other
work for the same user, and there is no deadline for a turn: put timeouts on your own model and
tool calls.

### Calling another agent

`ctx.peers` lists every other registered agent with its description; show them to your model in the
`send_to_agent` tool. `call_agent` returns the peer's answer, or one of these texts (it does not
raise for them):

- `error: unknown agent '<name>'`
- `error: you cannot call yourself`
- `error: call depth limit reached; answer your caller with what you have` (chains of calls are at
  most 4 deep unless the Backend sets `VDAGENT_MAX_DEPTH`)
- `error: calling <name> would deadlock (it is waiting on you); answer with what you have`
- `error: <name> failed: <reason>` when the peer's turn failed

Emit the text as the tool result either way; the model can adapt.

### Compaction

At the start of your turn, if this user has finished tasks whose messages are not summarised yet,
the Backend calls `await agent.compact(previous_summary, messages)` and stores the returned text as
the new `ctx.summary`.

- It has 150 s. Keep your model timeout below that (the bundled agents use 120 s, `LLM_TIMEOUT_S`).
- If `compact` raises, times out or returns something other than a string, the Backend logs
  `compaction of stack (<user>, <agent>) failed, continuing: <reason>`, runs the turn anyway and
  keeps those messages in `history`.
- Write a summary that stands alone: it is all later turns will know about those tasks.

### Cancellation and shutdown

When the user cancels the task or the Backend stops, your `invoke` receives
`asyncio.CancelledError` at its current `await`. Clean up and re-raise.

### MCP tools

`ctx.mcp` holds the URL and a bearer token of the Backend's MCP server for this turn. Connect over
MCP streamable HTTP with the header `Authorization: Bearer <token>`; the token stops working when
the turn ends. `tools/list` returns only the tools your agent is granted. Every tool, argument,
result field and error is described in `vdagent_backend.mcp.reference`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Log: `plugin vdagent_<name> failed: missing required environment variable …` | A setting is missing from `agents/<name>/.env`. | Copy `.env.example` to `.env` and fill it in. |
| Your agent is missing from the UI and from other agents' `ctx.peers` | The plugin failed to load, is not listed under `plugins:`, or has `enabled: false`. | Read the `plugin vdagent_<name> …` log line at startup. |
| `tools/list` returns nothing | Your agent name is not in `PERMISSIONS`. | Grant tools in `backend/vdagent_backend/mcp/tools.py`. |
| MCP requests get HTTP 401 `invalid_token` | The token was used after its turn ended. | Open the MCP session inside `invoke`. |
| Turn failed with `contract violation: …` | A requirement the Backend checks was broken. | Find the message under [Requirements the Backend checks](#requirements-the-backend-checks). |
| Turn failed with `INTERNAL: …` | `invoke` raised. | Turn tool failures into `error: …` results. |
| Turn failed with `DEADLINE_EXCEEDED: …` | You raised `AgentTimeoutError`. | Raise the model timeout or shorten the prompt. |
| A task stays running | A model, tool or peer call without a timeout. | Add timeouts; cancel the task in the UI. |
| `ctx.summary` never changes | `compact` fails. | Look for `compaction of stack … failed` in the log. |

## Testing

Test `invoke` without the Backend: pass any object with the `InvocationContext` fields and methods
that records what it receives, and assert the steps your agent emitted. Inject fakes for the model
and the MCP client through your agent's constructor, and keep `setup()` the only place that reads
settings. A recording fake does not check the requirements above unless you add those checks, so
also run your agent once against `make backend`.
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
"""Name of the tool that sends a message to another agent.

Offer your model a tool with exactly this name; its arguments are yours to design (the bundled
agents use `agent` and `message`). `InvocationContext.call_agent` accepts only tool calls with this
name. Give no other tool this name.
"""

Message = dict[str, Any]
"""One history message in the OpenAI chat-completions shape:

- `{"role": "user", "content": str}`: an incoming message, rendered `[from: <sender>] <text>`.
- `{"role": "assistant", "content": str | None, "tool_calls": [{"id": str, "type": "function",
  "function": {"name": str, "arguments": str}}]}`: `tool_calls` is present only when non-empty,
  and `content` is `None` when it is empty and tool calls are present.
- `{"role": "tool", "tool_call_id": str, "content": str}`: the result of one tool call.
"""


@dataclass(frozen=True)
class ToolCall:
    """One tool call of an assistant step, as passed to `InvocationContext.emit_assistant`."""

    id: str
    """Non-empty and unique within its step; use the id your model returned."""
    name: str
    """The tool name: an MCP tool, `send_to_agent`, or one of your local tools."""
    arguments_json: str
    """The arguments as the JSON object text your model produced. The Backend stores it as is."""


@dataclass(frozen=True)
class Peer:
    """Another registered agent this one can call through `send_to_agent`."""

    name: str
    """The value to pass as `target` to `InvocationContext.call_agent`."""
    description: str
    """What the agent does and returns, as its plugin registered it; show it to your model."""


@dataclass(frozen=True)
class McpEndpoint:
    """The Backend's MCP server for this turn.

    Connect over MCP streamable HTTP with the header `Authorization: Bearer <token>`. The token
    works only while the turn runs, and `tools/list` returns only the tools granted to your agent.
    Tools, arguments and results: `vdagent_backend.mcp.reference`.
    """

    url: str
    token: str


@dataclass(frozen=True)
class Note:
    """One memory note of a (user, agent) pair."""

    id: int
    kind: str
    """The label you gave it in `Memory.save` (default `note`)."""
    text: str
    created_at: str
    score: float | None = None
    """Set by `Memory.search`: cosine distance with an embedding, bm25 rank without one. Lower is
    better in both cases. `None` from `Memory.recent`."""


class Memory(Protocol):
    """Notes about one user, kept for your agent across turns and tasks.

    The Backend only stores and ranks notes. What to save, when to recall, and what reaches the
    model is your decision. If you use embeddings, compute them yourself with any model; searches
    only compare embeddings of the same length.
    """

    async def save(self, text: str, kind: str = "note", embedding: Sequence[float] | None = None) -> int:
        """Store a note and return its id.

        Raises `ValueError` for an empty `text` or `kind`, or an empty `embedding`.
        """
        ...

    async def search(self, query: str, limit: int = 5, embedding: Sequence[float] | None = None) -> list[Note]:
        """Return up to `limit` notes, best first.

        With `embedding`: the nearest notes by cosine distance, among notes saved with an embedding
        of the same length (`query` is ignored). Without: notes containing any word of `query`
        (the words are ORed; punctuation is ignored), ranked by bm25. A `query` with no words
        returns `[]`.
        """
        ...

    async def recent(self, limit: int = 10) -> list[Note]:
        """Return the newest `limit` notes, newest first."""
        ...

    async def delete(self, note_id: int) -> bool:
        """Delete a note. Returns False if it does not exist or belongs to another user or agent."""
        ...


class InvocationContext(Protocol):
    """What one turn knows, and the only way to report its progress. Built by the Backend.

    Every `emit_*` and `call_agent` call raises `ContractViolation` when it breaks a requirement the
    Backend checks, and after the turn has ended.
    """

    invocation_id: str
    """Id of this turn."""
    task_id: str
    """Id of the task (one user request) this turn belongs to."""
    user_id: str
    """The user the task belongs to."""
    summary: str
    """Summary of this user's earlier, compacted tasks with your agent; `""` if there is none. Put
    it in your system prompt."""
    history: list[Message]
    """This user's messages with your agent that are not in `summary` yet, oldest first. The last
    one is the message that started this turn."""
    peers: list[Peer]
    """Every other registered agent."""
    mcp: McpEndpoint
    """The Backend's MCP server and your token for this turn."""
    max_steps: int
    """How many assistant steps this turn may emit."""

    @property
    def memory(self) -> Memory:
        """This user's notes for your agent. The scope is fixed: you cannot read other users' or
        other agents' notes."""
        ...

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        """Record one model step, before any of its tool calls run.

        Returns once the step is stored and shown in the UI. A step without tool calls that is the
        last one when `invoke` returns is the turn's answer. `content` may be empty when there are
        tool calls.
        """
        ...

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        """Record the result of one tool call of the latest step. Use `error: <reason>` for a
        failure."""
        ...

    async def call_agent(self, tool_call_id: str, target: str, message: str) -> str:
        """Send `message` to agent `target` for the `send_to_agent` call `tool_call_id` and wait for
        its answer.

        Returns the peer's answer, or an `error: …` text when the Backend rejects the call (unknown
        agent, calling yourself, depth limit, deadlock) or the peer's turn fails. The answer is not
        recorded for you: pass it to `emit_tool_result(tool_call_id, answer)`.
        """
        ...


class Agent(Protocol):
    """What a plugin registers. One instance serves every turn, concurrently."""

    async def invoke(self, ctx: InvocationContext) -> None:
        """Run one turn, reporting every step through `ctx`; return after emitting the answer."""
        ...

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        """Fold `messages` of finished tasks into `previous_summary` and return the new summary.

        Called at the start of a turn, with 150 s to finish. On failure the Backend keeps the old
        summary and the messages stay in `history`.
        """
        ...


class PluginAPI(Protocol):
    """The handle `setup()` receives. Valid only while `setup` runs."""

    plugin: str
    """The module name from `config.yaml`."""
    log: logging.Logger
    """Logger `vdagent.plugin.<module>`."""

    def register_agent(self, *, name: str, description: str, agent: Agent) -> None:
        """Offer `agent` under `name`.

        Other agents see `description` in `ctx.peers`: say what the agent does and what it returns.
        Raises `ValueError` for an empty name or description, or a name that is already registered
        (by this plugin or an earlier one).
        """
        ...

    def on_shutdown(self, fn: Callable[[], Awaitable[None]]) -> None:
        """Run `fn` when the Backend stops, for example to close clients. Hooks run in reverse
        registration order, 5 s each."""
        ...


class PluginConfigError(Exception):
    """Raise from `setup()` for a missing or bad setting: the plugin is skipped and the Backend
    logs `plugin <module> failed: <message>`."""


class AgentTimeoutError(Exception):
    """Raise from `invoke` or `compact` when your model call times out; the turn fails with
    `DEADLINE_EXCEEDED: <message>`."""


class ContractViolation(Exception):
    """Raised by `ctx` when a turn breaks a requirement the Backend checks, or when `ctx` is used
    after the turn ended. The turn fails with `contract violation: <message>`, even if you catch
    it."""
