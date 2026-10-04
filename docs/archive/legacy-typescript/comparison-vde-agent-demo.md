# So sánh Team_6_cAi với vde-agent-demo

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

Bản so sánh kiến trúc module agent giữa Team_6_cAi (TypeScript) và vde-agent-demo (Python).

## 1. Kiến trúc tổng quan

### Team_6_cAi
- **Ngôn ngữ**: TypeScript, runtime Node.js
- **Contract**: `agent.v1` modules + ports
- **Entry points**: REST API (`/v1/agents/{id}/run`), worker, MCP server
- **Database**: PostgreSQL (durable ledger, evidence, receipts)
- **Registry**: `AgentRegistry` load từ `agents/manifests/*.json` (Python, `agent-runner.v2`)
- **Host factory**: `createHostPorts` bind ports vào `PiRuntime` + `McpToolPool`

### vde-agent-demo
- **Ngôn ngữ**: Python (uv workspace), runtime CPython 3.12
- **Contract**: plugin với `setup(api, opts)`
- **Entry points**: FastAPI backend (`vdagent_backend/api/rest.py`)
- **Database**: không durable (in-memory history + memory notes)
- **Registry**: `AgentRegistry` load từ `backend/config.yaml` plugins list
- **Plugin loader**: import module → `setup(api, opts)` → `api.register_agent(...)`

## 2. Cơ chế module/plugin

### Team_6_cAi: `agent.v1` module + ports

**Manifest** (`AgentManifest`):
```typescript
{
  apiVersion: "agent.v1",
  id: "reference.statistics",
  version: "1.0.0",
  displayName: "Statistics",
  inputSchema: Type.Object({ numbers: Type.Array(Type.Number()) }),
  outputSchema: Type.Object({ mean: Type.Number(), median: Type.Number() }),
  capabilities: ["data.analytics"],
  requiredPorts: ["model", "warehouse", "memory"],
  toolGrants: [
    { toolId: "warehouse.run_query", version: "1", effect: "read" },
    { toolId: "memory.search", version: "1", effect: "read" }
  ],
  limits: {
    timeoutMs: 30_000,
    maxModelCalls: 5,
    maxToolCalls: 10,
    maxCostUsd: 0.50
  }
}
```

**Execute function**:
```typescript
export async function execute(context: AgentContext): Promise<AgentResult> {
  // context.ports.model.complete(...)
  // context.ports.warehouse.query(...)
  // context.ports.memory.search(...)
  return { status: "completed", output, usage, evidence };
}
```

**Đăng ký**:
- Thêm manifest vào `AGENT_EXTERNAL_MANIFESTS`
- Production: `moduleAsPlugin(module)` wrap thành `AgentPlugin`
- Host factory kiểm tra `requiredPorts` có trong `WIRED_PORTS`; fail nếu unwired

**Ports abstraction** (7 ports):
1. `model`: LLM completion với schema validation
2. `tools`: MCP tool pool với grant intersection
3. `warehouse`: SQL sources catalog, describe, query
4. `artifacts`: binary storage (SHA-256 commit, sliced read)
5. `memory`: user notes (remember/search/forget)
6. `collaboration`: agent delegation (discover/invoke/wait/result)
7. `sandbox`: isolated command execution (Docker)

Mỗi port có uniform interface: `(input, options: {signal, deadline}) => PortResult<T>` với status `ok | denied | failed | unknown | queued`.

### vde-agent-demo: Python plugin

**setup function** (`agents/<name>/vdagent_<name>/__init__.py`):
```python
from vdagent_sdk import PluginAPI

def setup(api: PluginAPI, opts: dict) -> None:
    # Read config from agents/<name>/.env
    settings = read_settings()

    # Build agent brain (LiteLLM, LangChain, plain code, ...)
    agent = MyAgent(settings)

    # Register
    api.register_agent(
        name="data",
        description="Queries the sales warehouse",
        agent=agent
    )
```

**Agent interface** (`sdk/vdagent_sdk/__init__.py`):
```python
class Agent(Protocol):
    async def invoke(self, ctx: InvocationContext) -> None:
        # ctx.history: OpenAI chat dicts
        # ctx.memory.save(text, kind, embedding)
        # ctx.memory.search(query, limit, embedding)
        # await ctx.emit_assistant(content, tool_calls)
        # await ctx.emit_tool_result(tool_call_id, content)
        # reply = await ctx.call_agent(tool_call_id, target, message)
        pass

    async def compact(self, summary: str, messages: list) -> str:
        return new_summary
```

**Đăng ký** (`backend/config.yaml`):
```yaml
plugins:
  - module: vdagent_orchestrator
  - module: vdagent_data
    opts: {}
  - module: vdagent_report
    enabled: false
```

**Không có ports abstraction**: agent trực tiếp gọi:
- `ctx.emit_assistant(...)` / `ctx.emit_tool_result(...)` để viết history
- `ctx.call_agent(...)` để delegate
- `ctx.memory.save/search/delete(...)` cho memory
- MCP tools qua `ctx.mcp` URL + token (streamable HTTP SSE)
- Không có warehouse port: agent tự gọi MCP tools như `warehouse.run_query`

## 3. Tool grants và permissions

### Team_6_cAi
- **Manifest-level grants**: `toolGrants: [{ toolId, version, effect: "read" | "write" }]`
- **Runtime intersection**: host factory `gate()` checks:
  1. Port declared trong `requiredPorts`
  2. Tool granted trong `toolGrants`
  3. Tool trong pool allowlist cho agent scope
  4. `authorize()` callback pass
- **Fail-closed**: denied → agent thấy `{status: "denied", error: {code: "tool_not_granted"}}`

### vde-agent-demo
- **File-level grants**: `backend/vdagent_backend/mcp/tools.py`
  ```python
  PERMISSIONS = {
      "warehouse.run_query": ["orchestrator", "data"],
      "send_to_agent": ALL_AGENTS,
  }
  ```
- **Runtime check**: MCP server kiểm tra agent name trong allowlist
- **Fail-closed**: từ chối tool call nếu không trong list
- **Không có effect granularity**: read/write đều là "mutates" boolean per tool

## 4. Execution model

### Team_6_cAi
- **Synchronous run**: `POST /v1/agents/{id}/run` → `plugin.run(input, context)` → response
- **Background worker**: durable worker poll `platform_runs` với lease-based fencing
- **Checkpointing**: không hỗ trợ pause/resume (sandbox port trả `denied`)
- **Idempotency**: tool/port calls replay theo `idempotencyKey`
- **Evidence ledger**: evidence lưu ở bảng `evidence_refs` qua platform API

### vde-agent-demo
- **Async invoke**: `POST /api/tasks` → task_id → SSE `/api/tasks/{id}/events`
- **In-memory engine**: `vdagent_backend/engine/` quản lý turn, không durable
- **No checkpointing**: agent chạy đến khi trả reply hoặc fail
- **No idempotency**: restart task = chạy lại từ đầu với history cũ
- **No evidence ledger**: chỉ ghi history messages

## 5. Module lifecycle

### Team_6_cAi
```
Startup:
  ├─ Load manifests từ agents/manifests/
  ├─ activeModulePlugins(modules, versions.json enablement)
  │   └─ moduleAsPlugin(module) → kiểm tra requiredPorts wired
  └─ AgentRegistry.register(plugin)

Per request:
  ├─ createHostPorts(manifest, context)
  │   ├─ Bind identity: userId, spaceId, runId
  │   ├─ Inject UNTRUSTED_GUARD vào system prompt
  │   └─ Wire ports: model/tools/warehouse/artifacts/memory/collaboration/sandbox
  ├─ plugin.run(input, contextWithPorts)
  └─ Validate output schema → evidence → receipt
```

**Canary/rollback**: `AgentRegistry.updateActivation(id, version, "canary", {allowlist})` → traffic split → `rollback(id)` nếu alert.

### vde-agent-demo
```
Startup (backend/vdagent_backend/plugins.py):
  ├─ Read backend/config.yaml plugins list
  ├─ For each enabled plugin:
  │   ├─ importlib.import_module(spec.module)
  │   ├─ Call setup(api, opts)
  │   │   └─ api.register_agent(name, description, agent)
  │   └─ Commit registrations if setup returns normally
  └─ Fail: log "plugin <module> failed: <error>", skip it

Per task:
  ├─ engine.invoke_agent(name, message, user_id, task_id)
  │   ├─ Build InvocationContext (history, memory, mcp, peers)
  │   ├─ await agent.invoke(ctx)
  │   └─ Agent calls ctx.emit_assistant/emit_tool_result/call_agent
  └─ Broadcast events via SSE
```

**No canary**: disabled/enabled boolean trong config; thay đổi cần restart backend.

## 6. Testing strategy

### Team_6_cAi
- **Fake ports**: `src/testkit/` (model/tools/warehouse/artifacts/memory/collaboration/sandbox)
- **Contract validator**: `ContractValidator.validateManifest/Result/Evidence`
- **Port conformance**: `test/contract/port-conformance.test.ts` chạy matrix test cho mỗi port
- **Baseline receipts**: `pnpm baseline:postgres --task=M10` ghi golden output
- **Matrix compat**: `pnpm compat:matrix` kiểm tra cross-version

### vde-agent-demo
- **Unit tests**: pytest với mock `InvocationContext`
- **Integration tests**: `backend/tests/test_engine.py` spin up engine với fake agents
- **No receipts**: không có baseline verification
- **No contract validator**: schema validation nằm ở Pydantic/TypeBox trong agent code

## 7. Dependencies và boundaries

### Team_6_cAi
- **Boundary enforcement**: `pnpm boundary:check` chặn agent import host code
- **Agent chỉ import**: `src/contracts/index.ts` (manifest types, port interfaces)
- **Host owns**: identity, pool, runtime, ledger, observability, canary
- **Testkit**: fake implementations để agent test offline

### vde-agent-demo
- **SDK boundary**: plugins chỉ depend `vdagent_sdk`
- **Agent tự do import**: brain framework (LiteLLM, LangChain, OpenAI SDK, plain code)
- **Backend owns**: plugin loading, registry, history, turn rules R1–R11, MCP permissions
- **Không có testkit**: agent tự mock `InvocationContext`

## 8. Khi nào dùng cái nào?

### Dùng Team_6_cAi architecture khi:
- Cần **durable execution**: evidence ledger, receipts, replay
- Yêu cầu **high reliability**: canary deployment, rollback, baseline verification
- **Large scale**: nhiều agents chia sẻ infrastructure, quota enforcement
- **Compliance**: audit trail đầy đủ (evidence records, SHA-256 artifacts)
- **TypeScript ecosystem**: team quen Node.js, muốn type safety compile-time

### Dùng vde-agent-demo architecture khi:
- **Prototype nhanh**: import LangChain/LiteLLM, viết brain theo framework quen
- **Simple coordination**: 3–5 agents delegate message-based, không cần workflow phức tạp
- **Python ecosystem**: team quen Python, muốn dùng Hugging Face/scikit-learn/pandas
- **No durability need**: task chạy 1 lần, fail thì retry từ đầu
- **Flexible brain**: mỗi agent dùng framework khác nhau (LangChain vs plain OpenAI vs local model)

## 9. Migration path

**vde-agent-demo → Team_6_cAi**:
1. Viết `AgentManifest` cho mỗi agent (input/output schema, capabilities, limits)
2. Port `invoke()` logic sang `execute(context)` với ports API
3. Thay `ctx.emit_*` → port calls trả canonical result
4. Thay `ctx.call_agent` → `context.ports.collaboration.invoke`
5. Thay `ctx.memory.*` → `context.ports.memory.*`
6. Viết test với `src/testkit/`, chạy `pnpm baseline:postgres`
7. Đăng ký manifest qua `AGENT_EXTERNAL_MANIFESTS`

**Team_6_cAi → vde-agent-demo**:
1. Tạo plugin folder: `agents/<name>/vdagent_<name>/`
2. Viết `setup(api, opts)` load config từ `.env`
3. Port `execute()` logic sang `async invoke(ctx)` với `ctx` methods
4. Thay port calls → direct `ctx.emit_assistant/emit_tool_result/call_agent`
5. Thay warehouse port → MCP tool `warehouse.run_query` qua `ctx.mcp`
6. Thêm vào `backend/config.yaml`, grant tools trong `mcp/tools.py`

---

**Tóm lại**:
- **Team_6_cAi**: Production-grade, durable, ports abstraction, TypeScript, evidence-driven
- **vde-agent-demo**: Prototype-friendly, in-memory, direct context methods, Python, flexible brains

Chọn theo yêu cầu reliability, scale và ecosystem của team.
