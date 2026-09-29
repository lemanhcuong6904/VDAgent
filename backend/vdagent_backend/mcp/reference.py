# The MCP tools reference page for agent developers. The module docstring is rendered at import
# time from the tool catalog in `tools.py` (see `_render`); `make sdk-docs` publishes it with pdoc.

from __future__ import annotations

from typing import Any

from vdagent_backend.mcp import sql
from vdagent_backend.mcp.tools import (
    ALL_AGENTS,
    DEFAULT_PAGE_ROWS,
    MAX_PAGE_ROWS,
    PERMISSIONS,
    PREVIEW_ROWS,
    RESULT_FIELDS,
    TOOLS,
)

__all__: list[str] = []

_AGENT_ORDER = ("orchestrator", "data", "compare", "insight", "report")

_INTRO = f"""\
# MCP tools

The tools an agent calls through the Backend's MCP server during a turn: warehouse access,
datasets, charts and reports. This page is generated from the Backend's tool catalog
(`vdagent_backend/mcp/tools.py`), so it always matches the running Backend.

## Connect

Inside `invoke(ctx)`:

- **Where:** `ctx.mcp.url`, over MCP streamable HTTP.
- **Auth:** send the header `Authorization: Bearer <ctx.mcp.token>`.
- **When:** the token works only while this turn runs. Open the session inside `invoke` and close it
  before returning; a later request gets HTTP 401 `invalid_token`.
- **Which tools:** `tools/list` returns only the tools your agent may call (see
  [Who can call what](#who-can-call-what)). Give your model exactly those: their names,
  descriptions and input schemas are written for it.

```python
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

headers = {{"Authorization": f"Bearer {{ctx.mcp.token}}"}}
async with create_mcp_http_client(headers=headers) as http:
    async with Client(streamable_http_client(ctx.mcp.url, http_client=http), cache=None) as mcp:
        tools = (await mcp.list_tools()).tools
        result = await mcp.call_tool("run_query", {{"sql": "SELECT region, SUM(revenue) FROM sales GROUP BY region"}})
```

## Read a result

- **Success:** `is_error` is false and `content[0].text` is a JSON object. Its fields are listed under
  each tool below.
- **Failure:** `is_error` is true and the text is `error: <reason>`. Give that text to your model as
  the tool result and let the turn continue; the reason says what to fix.

Errors any tool can return:

| Text | Cause | Fix |
|---|---|---|
| `error: unknown tool '<name>'` | The name is not in the catalog. | Only offer names from `tools/list`. |
| `error: tool '<name>' is not available to the <agent> agent` | Your agent has no permission for it. | Ask a peer that has it, or grant it in `vdagent_backend/mcp/tools.py` (`ALL_AGENTS` or `PERMISSIONS`). |
| `error: '<arg>' is required and must be a non-empty string` (or `must be an integer`, `must be between …`, `must be a non-empty array of strings`) | A bad argument. | Follow the tool's input schema. |
| `error: dataset not found` | Wrong id, or the dataset belongs to another user. | Use an id created in this user's tasks. |

## Limits

- SQL runs for at most {sql.SQL_TIMEOUT_S:g} s: `error: query exceeded the {sql.SQL_TIMEOUT_S:g} s time limit`.
- A query stores at most {sql.MAX_ROWS:,} rows; `truncated` is true when rows were dropped. Aggregate
  in SQL instead of fetching raw rows.
- Dataset results show a preview of the first {PREVIEW_ROWS} rows. Read more with `get_dataset_rows`
  ({DEFAULT_PAGE_ROWS} rows by default, at most {MAX_PAGE_ROWS} per call).
- The Backend puts no timeout on the call on your side and does not shorten results. Set your own
  timeout and cut long results before they reach the model (the bundled agents use 30 s and
  16 000 characters followed by `…[truncated]`).

## Datasets, charts and reports

- Tools create artifacts with ids: datasets `ds_…`, charts `ch_…`, reports `rp_…`.
- An artifact belongs to the user of the task. Every agent working for that user can read it by id;
  other users get `not found`.
- Pass ids, not rows, when you message another agent: `send_to_agent` text stays short and the peer
  reads the data itself.
- In a report's markdown, `{{{{chart:<chart_id>}}}}` and `{{{{dataset:<dataset_id>}}}}` on their own
  lines embed a chart or a dataset table. `save_report` rejects ids that do not exist.
"""


def _agents() -> list[str]:
    known = [a for a in _AGENT_ORDER if a in ALL_AGENTS]
    return known + sorted(ALL_AGENTS - set(known))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _plain(text: str) -> str:
    """Tool and schema descriptions are plain text for models; keep `<id>` from reading as HTML."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _matrix() -> str:
    agents = _agents()
    lines = [
        "## Who can call what",
        "",
        "An agent that is not listed here sees no MCP tools. Grant tools in `vdagent_backend/mcp/tools.py`:"
        " add the agent to `ALL_AGENTS` for the tools every agent gets, and to `PERMISSIONS` for the others.",
        "",
        "| Tool | " + " | ".join(agents) + " |",
        "|---|" + "|".join(":-:" for _ in agents) + "|",
    ]
    for tool in TOOLS:
        marks = " | ".join("✓" if a in PERMISSIONS[tool.name] else "" for a in agents)
        lines.append(f"| [`{tool.name}`](#{tool.name}) | {marks} |")
    return "\n".join(lines)


def _type(spec: dict[str, Any]) -> str:
    kind = spec.get("type", "any")
    if kind == "array":
        return f"array of {spec.get('items', {}).get('type', 'any')}"
    return str(kind)


def _details(spec: dict[str, Any]) -> str:
    parts = [_plain(spec["description"])] if spec.get("description") else []
    if "enum" in spec:
        parts.append("One of " + ", ".join(f"`{v}`" for v in spec["enum"]) + ".")
    if "minimum" in spec and "maximum" in spec:
        parts.append(f"{spec['minimum']} to {spec['maximum']}.")
    elif "minimum" in spec:
        parts.append(f"At least {spec['minimum']}.")
    if "minItems" in spec:
        parts.append(f"At least {spec['minItems']} item(s).")
    if "default" in spec:
        parts.append(f"Default {spec['default']}.")
    return " ".join(parts)


def _arguments(schema: dict[str, Any]) -> str:
    properties: dict[str, Any] = schema.get("properties", {})
    if not properties:
        return "**Arguments:** none."
    required = set(schema.get("required", []))
    lines = ["**Arguments**", "", "| Name | Type | Required | Details |", "|---|---|:-:|---|"]
    for name, spec in properties.items():
        mark = "yes" if name in required else ""
        lines.append(f"| `{name}` | {_type(spec)} | {mark} | {_cell(_details(spec))} |")
    return "\n".join(lines)


def _returns(tool: str) -> str:
    lines = ["**Returns** (JSON object)", "", "| Field | Meaning |", "|---|---|"]
    lines += [f"| `{field}` | {_cell(meaning)} |" for field, meaning in RESULT_FIELDS[tool].items()]
    return "\n".join(lines)


def _tool_section(tool: Any) -> str:
    agents = ", ".join(a for a in _agents() if a in PERMISSIONS[tool.name])
    return "\n\n".join(
        [
            f"### `{tool.name}`",
            f"**Available to:** {agents}.",
            _plain(tool.description),
            _arguments(tool.input_schema),
            _returns(tool.name),
        ]
    )


def _render() -> str:
    tools = "\n\n".join(_tool_section(t) for t in TOOLS)
    return f"{_INTRO}\n{_matrix()}\n\n## Tools\n\n{tools}\n"


__doc__ = _render()
