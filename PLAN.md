# PLAN - Interface-First Agent Platform

> **Mục đích:** roadmap triển khai hoàn chỉnh để chuyển Team 6 cAi từ agent phụ thuộc
> `systemPrompt`/runtime nội bộ sang platform có interface ổn định. Đây là kế hoạch thực thi,
> không phải tuyên bố các mốc đã hoàn thành.
>
> **Cách dùng:** thực hiện theo thứ tự M0 -> M14. Chỉ đánh dấu `[x]` khi có code, test,
> tài liệu và receipt tương ứng. `[~]` là đang làm, `[!]` là bị chặn, `[ ]` là chưa làm.
> Không bỏ qua mốc phụ thuộc. Nếu phát hiện yêu cầu mới, ghi vào `docs/decisions/` và cập nhật
> mục "Change control" trước khi sửa contract.

## 0. Nguồn sự thật, phạm vi và trạng thái

### 0.1 Nguồn sự thật theo thứ tự ưu tiên

1. Code, migration và test đang chạy trong repository này.
2. `docs/architecture.md`, `docs/api.md`, `docs/agents.md`, `docs/tools.md`,
   `docs/agent-runner.md`, `docs/operations.md`, `docs/security.md` và
   `docs/folder-ownership.md` cho behavior hiện tại.
3. PLAN này cho kiến trúc đích và thứ tự chuyển đổi.
4. Tài liệu framework bên ngoài chỉ là bằng chứng thiết kế; không tự động trở thành dependency.

### 0.2 Kết quả mong muốn

- Một team chỉ cần viết `AgentModule`/`WorkflowModule` và test contract; không sửa API route,
  database private code, worker hoặc agent khác để thêm behavior.
- Agent có thể là code thuần, model-backed, graph/workflow, TypeScript process, Python process
  hoặc container; tất cả dùng cùng capability, deadline, cancellation, memory và audit boundary.
- Platform giữ identity, tenant scope, policy, quota, persistence, scheduling, retry, recovery,
  model/tool gateway, artifact ownership và observability.
- In-process, worker-process và container có cùng wire contract; thay runtime không thay semantics.
- PostgreSQL là source of truth cho run, attempt, step, event, outbox, memory revision, session,
  artifact metadata và authorization. Redis/NATS chỉ là transport/cache/wakeup có thể rebuild.

### 0.3 Không làm trong roadmap này nếu chưa có evidence

- Không tạo microservice riêng cho từng agent.
- Không cho model arbitrary shell, SQL, HTTP, filesystem, credential, Kubernetes hoặc publish tool.
- Không upload source/plugin/secret từ model hoặc browser để thực thi ngay.
- Không thêm LangGraph, Temporal, Kubernetes, vector database, Kafka/NATS hoặc A2A làm dependency
  runtime trước khi adapter contract và capacity/threat evidence chứng minh cần thiết.
- Không coi prompt, model output, memory, tool result, telemetry hay file input là trusted.

### 0.4 Trạng thái đã xác nhận từ lượt nghiên cứu này

- [x] Đọc toàn bộ tài liệu hiện hành trong `docs/` và code entrypoint/contract/test chính.
- [x] Loại tài liệu lịch sử không còn là source of truth: `docs/bug-check-2026-09-25.md`,
  `docs/research-adoption-plan.md`, `docs/developer-api.md`.
- [x] Đọc các dự án liên quan trong `/home/minh/projects/`: `rakazo`, `rakazo-new`, `oh-my-pi`,
  `pi-subagents`, `vde-agent-demo`, `OpenSandbox`, `agentbox`, `project-graph-agent`, `substrate`,
  `grok-bot` và inventory các dự án còn lại.
- [x] Đọc/đối chiếu tài liệu chính thức về LangGraph, Temporal, MCP, A2A, OpenAI Agents SDK,
  Google ADK, AutoGen, PydanticAI, LlamaIndex Workflows, Mem0, Graphiti/Zep, OpenTelemetry và
  NATS JetStream. Web connector không khả dụng trong phiên nghiên cứu; các URL chính thức được
  lưu ở mục 2 để người triển khai đọc lại khi cần.
- [ ] Chưa đánh dấu bất kỳ mốc code/runtime nào là hoàn thành chỉ vì đã đọc tài liệu.

## 1. Baseline repository và khoảng trống

### 1.1 Đang có và phải bảo toàn behavior

- TypeScript/Hono API, React/Vite frontend, PostgreSQL store/migrations và Docker Compose.
- `AgentPool`, `McpToolPool`, `ModelRegistry`, `WorkflowRegistry`, warehouse contract, artifact
  store, sandbox provider, run ledger, outbox, worker lease/fence và observability.
- Pi runtime/session adapter và `agent-runner.v1` JSONL process bridge.
- `src/agent-contract.ts`, `src/agent-sdk.ts`, `src/agents/factory.ts`, `src/agents/analytics.ts`,
  `src/tools/agent-delegation.ts`, `src/workflow.ts` và test parity hiện tại.

### 1.2 Gaps phải đóng

- `AgentContext` còn lộ runtime/pool private; SDK đã khai báo nhưng chưa là đường chạy chính.
- `defineAgent` và analytics còn prompt/router/config-id centric; agent code thuần hoặc workflow
  không có lifecycle chuẩn.
- Workflow mới mô tả DAG capability, chưa có typed state, executable node, checkpoint, approval,
  replan và durable child graph.
- Delegation còn hard-code orchestrator/depth; chưa có policy edge tổng quát cho mọi agent.
- `agent-runner.v1` chưa chuẩn hóa port call, checkpoint, streaming, typed error và resume.
- Memory/session/compaction cần scope, revision/CAS, trust classification, retention, export/delete
  và prompt budget rõ ràng.
- Artifact, receipt, evidence và telemetry cần phân biệt claim với proof, live status với durable state.

### 1.3 Quy tắc dependency direction

```text
agent package -> public contracts/sdk/testkit
platform host -> contracts + private adapters
adapter       -> external vendor SDK
API/worker    -> composition root + platform ports
agent package -X-> database, Pi session, MCP pool, Hono, process.env, raw filesystem
```

Import-boundary test phải fail nếu agent import private host module. Public SDK không được trả raw
Prisma/driver/session/pool; mọi dữ liệu ngoài process phải schema-validate và bounded.

## 2. Evidence matrix: cơ chế đã nghiên cứu và quyết định

| Cơ chế/nguồn | Điều lấy vào | Điều không bê nguyên | Quyết định/phase | Bằng chứng bắt buộc |
|---|---|---|---|---|
| LangGraph durable execution, checkpoints, interrupts, memory | graph state, checkpoint/resume, human interrupt, thread identity | Không khóa agent vào LangGraph; không để graph tự bypass policy | Adapter tùy chọn sau M5/M8 | replay deterministic, resume sau crash, interrupt authorization |
| Temporal workflows | workflow deterministic replay, activity boundary, signals/queries, retry policy | Không thêm Temporal server trước khi workload chứng minh cần; model/tool là nondeterministic activity | Semantics tham chiếu M6, adapter đánh giá M13 | replay fixture, signal ordering, idempotent activity |
| MCP specification | tools/resources/prompts, capability negotiation, versioning, auth/security boundary | MCP server không tự cấp tenant grant; không cho arbitrary resource URI | MCP là ToolPort/ResourcePort adapter M4 | schema/version/auth/size/timeout/unknown-field tests |
| A2A | Agent Card, task lifecycle, artifacts, streaming/status | Không mở public mesh; collaboration nội bộ vẫn server-authorized | A2A gateway chỉ là M12 external adapter | card compatibility, task correlation, auth/audience, artifact refs |
| OpenAI Agents SDK | tools, handoffs, guardrails, sessions, tracing | Không để SDK sở hữu policy hoặc persistence; model vendor là adapter | Model/handoff concepts dùng trong M3/M7 | guardrail denial, trace redaction, session replay |
| Google ADK | agent/workflow composition, sessions/state/memory, tool plugins | Không import ADK vào core; chỉ benchmark adapter | So sánh ở M13 | same task/output/cost/latency/conformance |
| Microsoft AutoGen/GraphFlow | team messages, sequential/parallel graph, termination conditions | Không để peer message là authority; không dùng terminal scrape | Collaboration semantics M6 | deadlock/fan-out/termination/failure isolation |
| PydanticAI | typed dependencies, result validation, durable execution/graph | Không để validation ở model prompt; không phụ thuộc Python runtime | Python SDK/reference M9 | schema rejection, dependency scope, retry classification |
| LlamaIndex Workflows | event/step/entry/exit, typed events, validation | Không dùng event bus làm source of truth; persisted event phải ở host | Workflow API M5 | event ordering, duplicate/replay, bounded payload |
| Mem0 | scoped memory, managed extraction/retrieval | Không gửi secret/PII/raw conversation vào hosted memory mặc định | Provider adapter M10 | consent, retention, export/delete, tenant isolation |
| Zep/Graphiti | temporal graph, incremental facts, hybrid retrieval | Graph không phải authorization; không auto-infer truth từ model | Optional semantic provider M10/M13 | provenance, temporal cutoff, stale fact handling |
| OpenTelemetry | traces/metrics/logs, context propagation, semantic attributes | Telemetry best-effort; không log prompt/secret/PII/raw chain | M11 | redaction, correlation, sampling policy, export outage |
| NATS JetStream | durable stream, ack/replay, consumer, at-least-once | Không thay PostgreSQL ledger; không giả exactly-once | Optional wake/event transport M11/M13 | duplicate ack, replay, outage rebuild |
| OpenSandbox | public API source of truth, control/data plane, snapshots, egress, isolation | Không triển khai microVM/K8s nếu threat/capacity chưa yêu cầu | SandboxProvider contract M9/M13 | isolation, resource limits, pause/resume, egress denial |
| agentbox | provider SDK boundary, lifecycle, checkpoint lineage, fresh identity on restore | Không copy provider internals; không reuse branch identity | M9 checkpoint contract | lineage, restore freshness, prune references |
| project-graph-agent | immutable receipts, Unknown state, verify/recheck artifacts, bounded I/O | Không coi claim/process exit là proof | M8/M11 | replay conflict, unknown reconciliation, hash/length |
| oh-my-pi/pi-subagents | append-only session tree, branch/compaction, durable child artifacts, bounded inspection | Memory luôn heuristic; observer không phải source of truth | M7/M10 | branch reconstruction, compaction gap, status replay |

URL đọc lại:

- LangGraph: <https://docs.langchain.com/oss/javascript/langgraph/durable-execution>,
  <https://docs.langchain.com/oss/javascript/langgraph/add-memory>
- Temporal: <https://docs.temporal.io/workflows>
- MCP: <https://modelcontextprotocol.io/specification/latest>
- A2A: <https://a2a-protocol.org/latest/specification/>
- OpenAI Agents SDK: <https://openai.github.io/openai-agents-js/guides/agents/>
- Google ADK: <https://google.github.io/adk-docs/>
- AutoGen: <https://microsoft.github.io/autogen/stable/>
- PydanticAI: <https://ai.pydantic.dev/>
- LlamaIndex: <https://docs.llamaindex.ai/en/stable/module_guides/workflow/>
- Mem0: <https://docs.mem0.ai/platform/overview>
- Graphiti: <https://help.getzep.com/graphiti/>
- OpenTelemetry: <https://opentelemetry.io/docs/>
- NATS JetStream: <https://docs.nats.io/nats-concepts/jetstream>

## 3. Kiến trúc đích

```text
Browser / API / MCP / A2A gateway / operator
                    |
              Auth + Task API
                    |
       Control plane (registry, grants, policy, quota,
       versions, migrations, canary, health, kill switch)
                    |
       Durable run/workflow engine (ledger, lease, fence,
       checkpoint, retry, wait, event, outbox, recovery)
                    |
       Runner adapter: in-process | process | container
                    |
       Public Agent SDK / Workflow SDK / protocol bridge
                    |
       Model | Tool/MCP | Warehouse | Artifact | Memory |
       Collaboration | Sandbox | Evidence | Telemetry ports
                    |
       PostgreSQL source of truth + object store + optional transport/cache
```

### 3.1 Host-owned responsibilities

Identity, tenant/audience, manifest activation, grant calculation, model policy, tool execution,
quota, deadline, cancellation, lease/fence, retries, checkpoint persistence, wait/wake, outbox,
artifact publication, memory scope/retention, audit, traces, rate limits, sandbox, migration,
backup, recovery and kill switch.

### 3.2 Agent-owned responsibilities

Input interpretation, domain reasoning, workflow state machine, prompt/skill bundle, model call
through `ModelPort`, tool selection through granted `ToolPort`, typed output/evidence references,
domain validation and explicit waiting/approval requests. Agent không sở hữu identity/policy/DB.

### 3.3 Modular monolith trước, extraction sau

Giữ host và adapters trong một deployable cho đến khi có số liệu về queue latency, CPU/memory,
blast radius, release cadence và security boundary. Khi tách service, giữ nguyên contract/event,
không tách chỉ vì folder đẹp.

## 4. Public interfaces và wire contract

Tên type có thể điều chỉnh khi code, nhưng field semantics và dependency direction là bắt buộc.
Schema JSON là source of truth; TypeScript/Python types được generate hoặc kiểm parity.

### 4.1 Manifest

```ts
interface AgentManifest<I, O> {
  apiVersion: "agent.v1";
  id: string; version: string; displayName: string;
  inputSchema: JsonSchema; outputSchema: JsonSchema;
  capabilities: string[]; requiredPorts: PortName[];
  toolGrants: ToolGrant[]; modelProfile?: string;
  workflow?: WorkflowManifest; limits: ExecutionLimits;
  compatibility: { minHostVersion: string; maxHostVersion?: string };
}
```

Manifest validation phải kiểm id/version/schema, capability existence, port availability, grant
subset, limits, dependency/license, no private import, no duplicate registration và deny dangerous
capabilities. Version execution được pin trong run; registry update không đổi run đang chạy.

### 4.2 Agent module và ports

```ts
interface AgentModule<I, O> {
  manifest: AgentManifest<I, O>;
  execute(ctx: AgentExecutionContext<I>): Promise<AgentResult<O>>;
}
interface AgentExecutionContext<I> {
  input: I; scope: AgentScope; ports: AgentPorts;
  signal: AbortSignal; deadline: number;
  emit(event: AgentEvent): Promise<void>;
  checkpoint(state: JsonValue): Promise<CheckpointRef>;
  wait(reason: WaitRequest): Promise<never>;
}
interface AgentPorts {
  model: ModelPort; tools: ToolPort; warehouse: WarehousePort;
  artifacts: ArtifactPort; memory: MemoryPort;
  collaboration: CollaborationPort; sandbox?: SandboxPort;
}
```

Port rules:

- `ModelPort.complete()` nhận schema, model profile, context refs, deadline; trả output, usage,
  finish reason, provider request id và classified error. Agent không chọn credential/provider tự do.
- `ToolPort.invoke()` chỉ nhận tool id đã grant, typed input, idempotency key; host injects actor,
  workspace, run, fence, audience, deadline. Tool output luôn bounded và có status/evidence refs.
- `WarehousePort` chỉ catalog/describe/query parameterized bounded; không raw SQL hoặc arbitrary URI.
- `ArtifactPort` publish metadata trước, stream bytes, verify SHA-256/length rồi mới `ready`;
  owner/scope/type/version bắt buộc; thiếu artifact là `unknown`, không tạo stream rỗng giả.
- `MemoryPort` expose search/read/remember/forget với scope, revision/CAS, provenance và retention;
  memory được đánh dấu untrusted data khi chèn vào prompt.
- `CollaborationPort` tạo child run qua server; không direct peer socket/database.
- `SandboxPort` chạy command từ allowlist, resource/egress policy, input/output caps, pause/resume;
  credential chỉ truyền bằng reference đến vault.

### 4.3 Result, error, evidence

```ts
interface AgentResult<T> {
  status: "completed" | "waiting" | "needs_approval" | "needs_input";
  output?: T; artifacts: ArtifactRef[]; evidence: EvidenceRef[];
  usage: UsageSummary; warnings: string[];
}
interface StructuredError {
  code: string;
  class: "validation" | "policy" | "transient" | "permanent" | "unknown";
  retryable: boolean; safeMessage: string; correlationId: string;
}
```

`claim`, `process_exit`, `observer_hint` và `receipt` là các loại bằng chứng khác nhau. Chỉ receipt
đã verify artifact/hash, run identity, fence và policy mới được dùng để đánh dấu thành công. State
`unknown` phải được giữ lại khi provider/network effect chưa thể xác minh.

### 4.4 Workflow và planner

```ts
interface WorkflowModule<S, O> {
  manifest: WorkflowManifest; execute(ctx: WorkflowContext<S>): Promise<WorkflowResult<O>>;
}
interface PlanSpec { version: "plan.v1"; nodes: PlanNode[]; edges: PlanEdge[]; budget: Budget; }
```

Planner/model chỉ đề xuất `PlanSpec`. Host validate schema, DAG/cycle, capability, tenant scope,
fan-out/depth, budget, side effects, approval và version trước khi schedule. Node phải có stable id,
input/output schema, timeout, retry class, compensation/unknown policy và checkpoint boundary.

## 5. State machine và persistence contract

### 5.1 Run lifecycle

`queued -> leased -> running -> waiting|completed|failed|cancelled|handed_off`.

- Retry transient tạo `Attempt` mới trên cùng `Run` và giữ manifest/model/tool version đã pin.
- Retry terminal hoặc input mới tạo linked `Run`; không ghi đè receipt cũ.
- `waiting` có reason `input|approval|children|tool|peer`; không giữ transaction/worker lease.
- Mỗi write kiểm `workspace_id`, `run_id`, `attempt_id`, `worker_id`, `fence`; stale worker bị reject.
- Handoff dùng CAS stage owner + terminal source + outbox, giới hạn depth/hop/bounce/dedup.
- Cancel là durable intent; provider không hỗ trợ cancel phải đi đến `unknown` và reconciliation.

### 5.2 Bảng/aggregate tối thiểu

- `agent_registry`, `agent_version`, `agent_activation`, `capability`, `grant`, `policy_revision`.
- `task`, `run`, `attempt`, `run_step`, `run_wait`, `run_checkpoint`, `run_child_edge`.
- `tool_execution`, `model_call`, `effect_ledger`, `run_event`, `outbox_event`, `audit_event`.
- `session`, `session_entry`, `session_branch`, `compaction`, `memory_item`, `memory_revision`.
- `artifact`, `artifact_part`, `evidence`, `provider_connection`, `secret_reference`.
- Unique/idempotency keys cho message, tool effect, event key, outbox delivery, artifact publication.

### 5.3 Event/outbox

- Ghi domain mutation + event journal + outbox trong cùng transaction.
- Event có `event_id`, `event_type`, schema version, aggregate/run id, sequence, causation,
  correlation, actor, audience và redacted metadata.
- Consumer at-least-once, idempotent; unknown event type/field được bỏ qua có metrics.
- Outbox retry có backoff/dead-letter/replay; không tự nhân side effect nếu effect chưa reconcile.
- Live status là projection; canonical status là ledger/event/checkpoint durable.

### 5.4 Checkpoint và session

- Checkpoint có schema/version, run/attempt/fence, parent/base, state hash, created_at, size.
- Restore tạo identity/branch mới; không tái sử dụng branch metadata của source.
- Session là append-only tree: entry id/parent id, active leaf, branch, compaction, reset boundary.
- Context reconstruction deterministic; blob lớn externalize sang artifact và giới hạn bytes.
- Compaction chỉ advance cursor qua sequence liên tục; gap/failure không được silently bỏ lịch sử.

## 6. Memory model hoàn chỉnh

### 6.1 Các lớp memory

1. **Working context:** input, tool results, current plan, ephemeral state; chỉ sống trong run.
2. **Session memory:** transcript tree, branch, compaction summary, reset boundary.
3. **Episodic memory:** run outcome, decision, evidence refs, failure/recovery receipt.
4. **Semantic memory:** fact/entity/relation có provenance, temporal validity, confidence và source.
5. **Procedural memory:** versioned skills, playbook, policy hint; không tự cấp quyền.
6. **Graph/index memory:** optional vector/FTS/temporal graph index, rebuildable từ canonical rows.

### 6.2 Scope và trust

Scope tối thiểu `workspace`, `conversation`, `user`, `bot`, `run`, `private`; mọi record có owner,
audience, sensitivity, source refs, revision, retention/deletion state. Private memory không vào
group prompt. Memory luôn là untrusted data; prompt wrapper phải chống instruction injection,
không cho memory thay thế policy/tool grant.

### 6.3 Memory provider interface

```ts
interface MemoryProvider {
  describe(): Promise<ProviderDescriptor>;
  read(ref: MemoryRef): Promise<MemoryRecord | null>;
  search(q: MemoryQuery): Promise<Bounded<MemoryHit>>;
  commit(req: MemoryCommit, expectedRevision?: number): Promise<MemoryRevision>;
  forget(ref: MemoryRef, mode: "tombstone" | "purge"): Promise<void>;
  export(scope: MemoryScope): AsyncIterable<MemoryExportRecord>;
  import(records: AsyncIterable<MemoryExportRecord>): Promise<ImportReceipt>;
}
```

Resolver tách `trust classification -> connection preparation -> provider creation`; credential
decode từ encrypted secret store, provider owner/deployment approval được kiểm trước khi load.
Local Markdown/SQLite, Postgres, hosted Mem0/Graphiti là adapter; không để agent biết adapter.

### 6.4 Retrieval, write và retention

- Search phải filter scope/audience trước ranking; hybrid/vector/graph chỉ xếp hạng trong tập hợp lệ.
- Hit có score, provenance, revision, valid_from/to, sensitivity và reason; không trả raw secret.
- Write dùng serializable transaction + expected revision/CAS; append revision history cùng mutation.
- Extraction background có lease/heartbeat, timeout, token/byte/concurrency cap và secret redaction.
- Retention job tombstone trước, purge theo legal/tenant policy, index rebuild sau; export/delete có audit.
- Context builder sort deterministic, byte/token cap, UTF-8 safe truncate; phân bổ budget system/tools/
  history/memory/results/output/margin và báo `needs_input` nếu mandatory evidence không fit.

### 6.5 Compaction

- `historyCompactedUpToSeq`, batch size, contiguous sequence check, summary max chars, transcript cap.
- Summary chứa coverage, source revisions, audience, generation id, CAS và evidence refs.
- Failure/retry không nhảy cursor; lease stale được reclaim; summary không được coi là authority.
- Test race, gap, duplicate, cancellation, retention, prompt escaping và replay reconstruction.

## 7. Tool, model, connector và sandbox platform

### 7.1 Registry/grant

- Tool manifest: id/version, input/output JSON Schema, effect class (`read|write|external`), limits,
  required capability, idempotency/compensation, sensitivity, timeout và provider adapter.
- Default deny; grant là intersection của actor, tenant, agent manifest, task, delegation edge,
  audience và policy revision. Child grant chỉ là subset parent; helper read-only.
- Registry kiểm schema/version/size/deadline/fence trước handler; handler không tự quyết authorization.
- Tool result union `ok|queued|needs_approval|needs_input|denied|failed|unknown`, có evidence/limitations.

### 7.2 Model gateway

- Model profile pin provider/model/version, context/output cap, price, region, safety, timeout và retry.
- Provider credential chỉ adapter; no model id from untrusted user without registry lookup.
- Structured output validate schema; malformed output là classified error, không tự sửa im lặng.
- Usage ledger gồm input/output/cache tokens, latency, cost estimate, provider request id và budget.
- Retry chỉ provider transient; side effect/tool calls tách activity; model call replay fixture deterministic.

### 7.3 MCP/resource connector

- MCP client negotiate protocol/version/capabilities, validate tool/resource schema, timeout, auth,
  origin/audience, URI allowlist và output cap.
- MCP server không được mở database/credential ngoài grant; host owns tenant/policy.
- Provider outage, protocol mismatch, oversized/unknown response đều có conformance test và safe error.

### 7.4 Sandbox/process/container

- `ProcessRunner` v2 message types: hello/welcome, invoke, port_call, port_result, event,
  checkpoint, wait, cancel, result, failure, heartbeat; sequence/idempotency/correlation bắt buộc.
- Python/TS SDK generated từ cùng schema; v1 chỉ compatibility adapter.
- Sandbox lifecycle `created|running|paused|stopped|destroyed`; pause/resume/checkpoint semantics rõ.
- Enforce CPU/memory/disk/time/output/FD/process limits, no unrestricted network, egress allowlist,
  credential references, filesystem mount policy và kill on deadline.
- Restore tạo fresh branch/worktree identity; prune chỉ artifact không còn reference.

## 8. Collaboration, A2A và workflow graph

### 8.1 Nội bộ

`discover -> invoke(sync|async) -> wait -> result`; parent/child edge durable, typed input/output,
deadline, depth/fan-out/total budget và trace context. Không truyền payload tùy ý qua database.

### 8.2 Mailbox và handoff

Request/question wake peer; status/fyi không tự tạo chatter. Result wake correlated waiter. Handoff
CAS stage owner, terminal source và target; chống loop/bounce, max hop và duplicate effect.

### 8.3 Deadlock và termination

- Theo dõi wait-for graph; reject cycle trước khi block.
- Sync call khi target busy chuyển queue/async hoặc fail rõ; không giữ parent transaction.
- Workflow termination condition phải deterministic; child failure policy (`fail_fast|join|compensate`)
  khai báo trong manifest.

### 8.4 External A2A adapter

Chỉ bật sau M12 khi có auth/audience/tenant mapping, Agent Card version, task/artifact correlation,
stream reconnect và rate limit. Public A2A không được cấp quyền nội bộ vượt policy.

## 9. Security và threat model

- Threats: prompt injection từ memory/tool/file, confused deputy, cross-tenant IDOR, stale worker,
  replay/duplicate effect, malicious plugin, secret exfiltration, SSRF/MCP resource abuse, sandbox
  escape, artifact substitution, log leakage, provider unknown effect, denial by fan-out.
- Identity: actor/tenant/workspace/conversation/run/audience đều server-derived; host-selected scope
  không phải authentication.
- Plugin isolation: signed/allowlisted package, API version gate, denylist imports, dependency scan,
  secret scan, resource limits, canary và kill switch.
- Data: encrypt secret/artifact at rest/in transit, KMS/vault reference, PII redaction, retention,
  deletion tombstone, no raw prompt/chain-of-thought in logs.
- Authorization: policy checked at API, planner, port and effect boundary; read/write/approve/publish
  distinct; human approval không bị bot giả danh.
- Supply chain: lockfiles, hash/pin image/provider, SBOM/license, vulnerability scan, reproducible build.
- Audit: immutable decision/effect/approval/recovery receipts; tamper-evident hash chain nếu cần.
- Unknown: external claim/receipt mismatch giữ `unknown`, yêu cầu reconcile; không retry/relaunch mù.

## 10. Observability và vận hành

- Correlation tuple `tenant, actor, task, run, attempt, step, worker, fence, trace` trên mọi event.
- Metrics: queue age, lease expiry, run latency, retry, wait age, token/cost, tool error, memory hit,
  compaction, artifact verify, outbox lag, sandbox resource, policy denial, unknown rate.
- Traces/spans qua model/tool/child/sandbox/provider; attributes allowlist, prompt/content redacted.
- Logs structured, bounded, no secret/PII/raw model reasoning; telemetry exporter outage không làm fail run.
- Alerts: stale lease, outbox dead-letter, DB pool, artifact mismatch, tenant denial spike, cost budget,
  memory compaction gap, provider unknown, sandbox escape signal.
- Runbooks: startup/shutdown, migration, worker drain, replay outbox, reconcile unknown, restore DB,
  rotate secret, disable agent/version/provider, rollback canary, purge memory/artifact.

## 11. API/UI compatibility

- Giữ endpoint hiện tại qua `LegacyAgentAdapter`; response/event shape có version và deprecation window.
- Thêm registry/manifest/activation/plan/run/step/checkpoint/memory/evidence endpoints sau contract.
- UI chỉ hiển thị authorized projection: run timeline, child graph, wait/approval, artifacts/evidence,
  cost/usage và error; không hiển thị raw prompt/secret/private memory.
- Streaming dùng cursor/replay và reconnect; event unknown bị bỏ qua có warning, không crash client.
- API error map ổn định: validation, auth, policy, conflict, unavailable, unknown; mọi request có idempotency.

## 12. Test strategy và bằng chứng

### 12.1 Tầng test

- Unit: state machine, budget, schema, grant intersection, memory scope/CAS, planner validator.
- Contract: TypeScript/Python/process/provider/MCP/A2A schema, version, unknown field, size/deadline.
- Integration: PostgreSQL migrations/RLS/lease/fence/outbox, object store hash, Redis rebuild.
- Recovery: crash trước/sau commit, stale worker, duplicate delivery, provider timeout/429/unknown,
  process reconnect, compaction gap, artifact partial upload.
- Security: tenant/audience/IDOR, prompt injection, SSRF, secret/log leakage, plugin import, sandbox egress.
- E2E: create task -> agent -> tool/model -> child -> memory -> artifact -> UI/audit.
- Load/soak: concurrency, fan-out, queue latency, memory/CPU, cost budget, outbox lag.
- Eval: golden tasks, abstention, evidence correctness, context compaction, deterministic replay.

### 12.2 Receipt bắt buộc

Mỗi checklist item tạo `docs/execution/receipts/<milestone>.json` gồm task id, baseline git SHA,
owner/reviewer, commands/exit codes, environment, versions, artifacts+SHA256, limitations, rollback
result và thời gian. Không lưu secrets/PII. PASS không hợp lệ nếu chỉ có log tự khai hoặc skipped test.

### 12.3 Lệnh gate

```sh
corepack pnpm check
corepack pnpm lint
corepack pnpm test
corepack pnpm frontend:build
npm --prefix frontend test
git diff --check
```

Integration/process/container/load chỉ chạy khi dependency/service tương ứng sẵn sàng; nếu chưa có
phải ghi `NOT_RUN`/`BLOCKED`, không giả PASS.

## 13. Roadmap triển khai có checkbox

Mỗi mốc dưới đây là một PR/commit logic nhỏ. `Deps` phải PASS trước khi bắt đầu. `Files` là vùng
đích tối thiểu; được thêm file test/receipt/runbook tương ứng.

### M0 - Baseline, governance và schema source of truth

**Deps:** không. **Files:** `PLAN.md`, `docs/decisions/`, `docs/execution/`, `package.json`, `scripts/`.

- [x] M0.1 Ghi inventory code, docs, exports, registrations, DB tables, worker paths và current test matrix.
- [x] M0.2 Chốt schema toolchain, Node/TS, lockfile, database và protocol version; không dùng `latest`.
- [x] M0.3 Tạo JSON Schema conventions (IDs, version, timestamps, errors, bounds, unknown fields).
- [x] M0.4 Tạo receipt JSON Schema + validator; phân biệt `PASS/FAIL/BLOCKED/NOT_RUN`.
- [x] M0.5 Tạo `PROGRESS.md`, `BLOCKERS.md`, `CHANGE_REQUESTS.md`, ownership/approver matrix. (2026-09-28: `BLOCKERS.md` gộp vào mục "Việc còn mở" của `PROGRESS.md`.)
- [x] M0.6 Thêm import-boundary/static checks, secret scan, dependency/license/SBOM check.
- [x] M0.7 Chụp baseline test/lint/typecheck và lưu command/output hash.

**PASS:** schema lint deterministic; baseline xanh hoặc blocker có receipt; không thay behavior.

Local technical gate verified: `docs/execution/M0-audit.md`, receipt `docs/execution/receipts/M0.json`.
Reviewer là Codex self-review; không phải human merge/release approval.
**Rollback:** chỉ revert scripts/docs/schema mới, không đụng data migration.

### M1 - Public contract package và testkit ✓

**Deps:** M0. **Files:** `src/contracts/`, `src/testkit/`, `schemas/`, `docs/public-contracts.md`
**Completed:** 2026-09-27 (technical self-review; human/release approval vẫn pending).

- [x] M1.1 Định nghĩa `AgentManifest`, `AgentModule`, `AgentScope`, `AgentResult`, `StructuredError`; workflow metadata canonical trong `agent-manifest.v1`; executable plan semantics thuộc M5 (`src/workflow/workflow-module.ts`).
- [x] M1.2 Định nghĩa `ModelPort`, `ToolPort`, `WarehousePort`, `ArtifactPort`, `MemoryPort`,
  `CollaborationPort`, optional `SandboxPort`.
- [x] M1.3 Định nghĩa event/error/checkpoint/wait/usage/evidence/artifact schemas.
- [x] M1.4 Generate TypeScript types và Python/reference JSON types; parity test. `agent-protocol.v2`
  đã chuyển sang Draft 2020-12 canonical (`urn:team6:schema:agent-protocol:v2`); full
  `schema:check`/`contracts:check` (14 generated files) PASS.
- [x] M1.5 Tạo fake ports deterministic, bounded và fault-injectable (ContractTestKit): bảy ports trong `src/testkit/`.
- [x] M1.6 Conformance cases cho timeout, cancellation, scope, output limit, unknown fields:
  `test/contract/port-conformance.test.ts` chạy cùng 8 case cho cả bảy ports (56 tests).

**Bằng chứng:**

- `src/contracts/index.ts` là barrel canonical; generated vocabulary lấy từ JSON Schema Draft 2020-12.
- `test/contract/protocol-schema.test.ts` validate frame của TS runtime và Python SDK theo schema
  v2; parser vẫn giữ unknown fields (forward-compatible), schema đóng cho known fields.
- Python SDK: `schema("agent-protocol")` trả resource v2; checkpoint manifest bỏ field `None`
  thay vì ghi `null` trái schema.
- Artifact fake trả `unknown` (không phải empty success) cho artifact ID không tồn tại; matrix ghi
  nhận đây là ngoại lệ có chủ đích.
- Receipt: `docs/execution/receipts/M1-<timestamp>.json` (xem PROGRESS.md), tạo bằng
  `pnpm baseline:postgres -- --task=M1 --rollback=<rehearsal script> --reviewer=...`.

**PASS:** contract package generated/versioned/tested độc lập; conformance matrix đủ bảy ports.
**Rollback:** rehearsal đã chạy PASS (log `rollback-tests` trong receipt M1): khôi phục draft-07 schema, bỏ
generated export; typecheck và runtime protocol tests vẫn PASS. Các milestone sau phụ thuộc `src/contracts/`, nên không rollback toàn M1.

### M2 - Host SDK adapter và legacy bridge ✓

**Deps:** M1. **Files:** `src/ports/`, `src/contracts/`, tests. **Completed:** 2026-09-26

- [x] M2.1 Implement adapter từ runtime/tool pool/warehouse/artifact/memory hiện tại sang ports.
- [x] M2.2 Inject SDK vào API, durable worker và process runner cùng một factory. `src/ports/host-factory.ts`
  (`createHostPorts`) dùng chung cho `AgentModule` trong `AgentPool` (`src/ports/module-plugin.ts`) và process
  agent `protocol: "agent-runner.v2"` (`src/registry.ts`); `pnpm compat:matrix`: M2 `WIRED`. Fence của legacy run
  chưa truyền vào port (scope fence cố định `1`), nên stale-fence rejection vẫn thuộc durable workflow host.
- [x] M2.3 Implement `LegacyAgentAdapter`; giữ output/event/error parity.
- [x] M2.4 Bỏ raw pool/runtime khỏi public `AgentContext`; private context chỉ nằm trong bridge.
- [x] M2.5 Chuyển một agent deterministic nhỏ sang `AgentModule` reference.
- [x] M2.6 Test in-process và legacy path cùng fixture cho success/failure/cancel/timeout.

**PASS:** agent mới chỉ import SDK public; roster cũ không đổi; stale grant/fence bị reject.
**Rollback:** feature flag chạy legacy adapter, không migration data.

**Evidence:**
- Port adapters: `src/ports/{model,tool,warehouse,artifact,memory,collaboration,sandbox}-port.ts`
- Factory: `src/ports/index.ts` with `createPorts()` and `PortFactoryConfig`
- Legacy bridge: `src/ports/legacy-bridge.ts` with `LegacyAgentAdapter`, `LegacyAgentRegistry`
- Tests: `test/contract/ports.test.ts` (14 tests passing)
- Schema exports: `src/contracts/index.ts` with all required validation schemas
- Documentation: `docs/public-contracts.md` (nội dung còn đúng của `docs/ports-integration.md` đã gộp vào đây ở M14.2)
- All contract tests passing: 106/111 tests (5 skipped), 34/36 test files

### M3 - Registry, manifest, policy và model gateway

**Deps:** M1-M2. **Files:** `src/registry/`, migrations/tests.

- [x] M3.1 Registry version pin, manifest validation, activation state `pending/canary/enabled/disabled`.
- [x] M3.2 Capability/grant intersection ở API, planner, port và effect boundary. API: `descriptor.tools` ∩ pool;
  planner: catalog loại agent không nhận delegation; port/effect: manifest `toolGrants` ∩ pool allowlist mỗi lần gọi
  (`test/ports/host-factory.test.ts`). `src/registry/policy-engine.ts` vẫn chưa nối (policy revision nâng cao).
- [x] M3.3 Model profile/provider adapter, schema output validation, usage/cost/deadline ledger.
- [x] M3.4 Policy revision pin trong run; activation không đổi run đang chạy.
- [x] M3.5 Canary/allowlist/kill-switch, per-agent health check và rollback retention.
- [x] M3.6 Negative tests: unauthorized capability, version mismatch, budget, tenant/audience leakage.

**Evidence:** `src/registry/agent-registry.ts`, `src/registry/model-registry.ts`, `src/registry/policy-engine.ts` với 61 tests pass. AgentRegistry xử lý version/activation/canary/rollback; ModelRegistry xử lý profile/provider/usage/cost/schema validation; PolicyEngine xử lý capability/grant intersection, policy pin, tenant isolation và audience leakage.

**PASS:** add/disable/rollback registry không sửa route/orchestrator; model không tự chọn credential.
**Rollback:** disable version và route traffic về previous compatible version.

### M4 - Tool/MCP/connector interface

**Deps:** M1-M3. **Files:** `src/tool-pool.ts`, `src/mcp-client-tool.ts`, `src/mcp-server.ts`, schemas/tests.

- [x] M4.1 Chuẩn hóa tool manifest, effect class, idempotency, compensation, limits và sensitivity.
- [x] M4.2 Host inject `ToolContext`; schema/deadline/size/fence/grant check trước handler.
- [x] M4.3 MCP capability/version/auth/resource URI allowlist và output bounds.
- [x] M4.4 Tool result union và evidence/limitation/unknown semantics.
- [x] M4.5 Conformance cho duplicate side effect, protocol mismatch, timeout, oversized response, SSRF.
- [x] M4.6 Migrate tối thiểu một read tool và một write tool qua `ToolPort`.

**PASS:** không có arbitrary tool/SQL/HTTP/shell; tool replay không nhân side effect.
**Rollback:** route tool qua legacy pool với policy check giữ nguyên.

### M5 - Workflow graph, planner và checkpoint API

**Deps:** M2-M4. **Files:** `src/workflow.ts`, `src/planner.ts`, `src/run-state.ts`, migrations/tests.

- [x] M5.1 Định nghĩa `WorkflowModule`, typed state, `PlanSpec`, node/edge schema và stable node id.
- [x] M5.2 Validator DAG/cycle, capability/scope, budget, fan-out, side effect và approval.
- [x] M5.3 Node lifecycle start/checkpoint/wait/resume/complete/fail/cancel/replan.
- [x] M5.4 Persist parent/child/step/checkpoint/usage/event với manifest/policy pin.
- [x] M5.5 Planner chỉ đề xuất plan; host là authority schedule/approval.
- [x] M5.6 Replay/determinism tests và compatibility với `WorkflowRegistry` cũ.

**PASS:** workflow typed chạy lại sau crash; invalid plan bị reject trước side effect.
**Rollback:** feature flag giữ planner cũ, không xóa workflow records.

### M6 - Durable run engine, worker recovery và collaboration

**Deps:** M3-M5. **Files:** `src/run-ledger.ts`, `src/run-worker.ts`, `src/outbox.ts`,
`src/tools/agent-delegation.ts`, migrations/tests.

- [x] M6.1 Hoàn thiện state machine, lease/heartbeat/fence và stale-write rejection.
- [x] M6.2 Transactional event+outbox, idempotent consumer, replay/dead-letter/reconcile.
- [x] M6.3 Implement `CollaborationPort` discover/invoke/wait/result từ policy edge.
- [x] M6.4 Typed child run, depth/fan-out/budget/deadline/trace; remove orchestrator hard-code.
- [x] M6.5 Mailbox question/result/wake, handoff CAS, bounce/dedup và wait-for cycle rejection.
- [x] M6.6 Fault tests: crash before/after commit, Redis loss, duplicate, stale lease, child failure.

**PASS:** agent bất kỳ có grant có thể gọi agent khác; recovery tạo đúng một durable outcome.
**Rollback:** disable collaboration hoặc revert host adapter; giữ child records/audit.

### M7 - Session tree, context builder và compaction

**Deps:** M5-M6. **Files:** `src/pi-session-store.ts`, `src/memory-store.ts`, `src/agent-guardrails.ts`, tests.

- [x] M7.1 Append-only entries, parent/leaf/branch/reset/compaction schema và deterministic reconstruction.
- [x] M7.2 Context budget system/tools/history/memory/results/output/margin; no silent mandatory drop.
- [x] M7.3 Compaction cursor contiguous check, CAS, lease/heartbeat/retry/gap behavior.
- [x] M7.4 Externalize oversized blobs to verified artifacts; bound inspection/event payload.
- [x] M7.5 Branch/fork/restore tests, provider failure, duplicate compaction và retention.

**PASS:** session replay byte-equivalent trong fixture; compaction không tạo history gap.
**Rollback:** disable background compaction; retain raw transcript/cursor.

### M8 - Memory providers và lifecycle

**Deps:** M7. **Files:** `src/memory-store.ts`, `src/contracts/memory*`, migrations, provider adapters/tests.

- [x] M8.1 Implement provider-neutral `describe/read/search/commit/forget/export/import`.
- [x] M8.2 Scope/audience/sensitivity/retention/revision/CAS và transactional revision history.
- [x] M8.3 Resolver trust classification, encrypted credential reference, deployment-owner approval.
- [x] M8.4 Implement local deterministic provider; optional Postgres/Markdown adapter parity.
- [x] M8.5 Retrieval filter-before-rank, provenance, temporal cutoff, bounded hybrid search.
- [x] M8.6 Background extraction lease, redaction, token/byte/concurrency cap, stale cleanup.
- [x] M8.7 Test tenant isolation, prompt injection, edit/delete/revoke, export/import/delete audit.

**PASS:** bot/user/private memory tách đúng; provider outage không làm leak hoặc corrupt revision.
**Rollback:** disable provider, fallback read-only/local provider, giữ canonical records.

### M9 - Process SDK v2, sandbox và checkpoint lineage

**Deps:** M2, M6-M8. **Files:** `src/agent-runner.ts`, `sdk/`, `src/sandbox*.ts`, protocol schemas/tests.

- [x] M9.1 Versioned JSONL/bidi protocol hello/invoke/port_call/event/checkpoint/wait/cancel/result.
- [x] M9.2 Generate/align Python and TypeScript SDK; unknown fields forward-compatible.
- [x] M9.3 Host-side authorization for every port call; sequence/idempotency/correlation checks.
- [x] M9.4 Process crash/reconnect/resume; v1 compatibility adapter and explicit quarantine on mismatch.
- [x] M9.5 Sandbox resource/egress/filesystem/credential reference policy and lifecycle states.
- [x] M9.6 Checkpoint manifest parent/base/source/hash; restore fresh identity; safe prune.
- [x] M9.7 Contract tests in-process vs process vs container, including cancel/unknown effect.

**PASS:** external agent không cần private API; worker restart giữ checkpoint/run semantics.
**Rollback:** route to v1 runner; disable external activation; preserve artifacts.

### M10 - Agent module migration và workflow-owned behavior

**Deps:** M2, M5-M9. **Files:** `src/agents/`, `src/workflow.ts`, `src/tools/`, docs/tests.

- [x] M10.1 Tách `data`, `compare`, `insight`, `visualize`, `report` khỏi `analytics.ts`.
- [x] M10.2 Convert mỗi behavior thành module/manifest/schema/evidence contract riêng.
- [x] M10.3 Replace `config.id` routing/keyword heuristic bằng registry capability/planner. Routing theo capability
  `workflow.plan`; xóa nhánh keyword `isAnalyticsRequest`/`runAnalyticsWorkflow`; host luôn inject catalog từ registry.
  Fallback còn lại là `buildCapabilityPlan` của planner (host-validated, M5).
- [x] M10.4 Migrate model-backed, code-only và workflow-backed reference agents.
- [x] M10.5 Parity E2E cho output/artifact/error/event của roster cũ.
- [x] M10.6 Onboard một agent team mới chỉ bằng package + manifest + tests + registry entry.

**PASS:** thêm agent không sửa orchestrator/API/database private; old runs replay được.
**Rollback:** per-agent legacy adapter và canary disable.

### M11 - Evidence, artifact, audit và observability production boundary

**Deps:** M3-M10. **Files:** `src/warehouse-artifacts.ts`, `src/audit.ts`, `src/observability.ts`,
`src/metrics.ts`, migrations/runbooks/tests.

- [x] M11.1 Metadata-first artifact publication, SHA-256/length readback, owner/isolation/version.
- [x] M11.2 Evidence refs link source/run/tool/model/artifact revision; missing evidence = unavailable.
- [x] M11.3 Immutable terminal receipt, identical replay no-op, changed replay conflict.
- [x] M11.4 OTel traces/metrics/logs with redaction, correlation and exporter-failure isolation.
- [x] M11.5 Observatory projection: timeline, graph, usage, wait, error, recovery; no raw prompt.
- [x] M11.6 Alerts/runbooks for stale leases, outbox lag, unknown, cost, artifact mismatch, PII leak.

**PASS:** reviewer can verify success from durable receipt/evidence; telemetry cannot authorize action.
**Rollback:** disable exporter/projection only; keep journal/audit canonical.

### M12 - API/UI, MCP và A2A compatibility surface

**Deps:** M4, M6, M11. **Files:** `src/web-api.ts`, `src/mcp-server.ts`, `frontend/`, schemas/docs/tests.

- [x] M12.1 Versioned registry/activation/plan/run/step/checkpoint/memory/evidence endpoints.
- [x] M12.2 Idempotency/error/cursor/replay/reconnect semantics; preserve old endpoints via adapter.
- [x] M12.3 UI authorized projections for run graph, approval, artifacts, evidence, cost and errors.
- [x] M12.4 MCP server resources/tools with auth/audience/size/version contract.
- [x] M12.5 Optional A2A gateway: Agent Card, task/artifact streaming, auth, rate limit, tenant mapping.
- [x] M12.6 Browser/API security negatives and event unknown-field compatibility.

**PASS:** UI/API reconnect/replay không mất event; external protocol không mở quyền nội bộ.
**Rollback:** hide new routes/feature flag; keep old API projection.

### M13 - Deployment, scale, backup và disaster recovery gates

**Deps:** M6, M9, M11-M12. **Files:** `docker-compose.yml`, `docker/`, `docs/operations.md`,
`docs/security.md`, scripts/CI/runbooks.

- [x] M13.1 Health/readiness/liveness, graceful worker drain, migration lock và startup order.
- [x] M13.2 Postgres backup/restore, artifact hash restore, outbox/session/effect recovery rehearsal.
- [x] M13.3 Capacity test for API/worker/child fan-out/model/tool/memory/artifact; record p95/cost.
- [x] M13.4 Redis/cache/transport loss and rebuild from Postgres; no source-of-truth drift.
- [x] M13.5 Security scan, SBOM/license, image pin, secret rotation, egress/sandbox review.
- [x] M13.6 Canary deploy, migration observation window, rollback rehearsal, kill-switch drill.
- [x] M13.7 Decide with evidence whether external workflow engine, NATS, vector/graph store or
  microservice extraction is justified; otherwise keep adapters optional and record rejection.

**PASS:** measured recovery/capacity/security receipts; no production-ready claim without external gates.
**Rollback:** restore previous image/schema-compatible version; pause new activations.

### M14 - Handover, documentation và definition of done

**Deps:** M0-M13. **Files:** all maintained docs, `docs/execution/`, ownership files, release checklist.

- [x] M14.1 Update `docs/README.md`, `agents.md`, `tools.md`, `agent-runner.md`, `api.md`,
  `architecture.md`, `operations.md`, `security.md` to match code and contract versions. Docs nêu rõ production
  vẫn chạy `AgentPlugin`/v1; contract stack mới là `LIBRARY_ONLY` theo `pnpm compat:matrix`.
- [x] M14.2 Remove stale/duplicate docs only after links/search confirm no source-of-truth loss. `contracts-overview.md`,
  `ports-integration.md` gộp vào `public-contracts.md`; link đã sửa; xóa cùng receipt/log thừa theo owner duyệt.
- [x] M14.3 Publish agent authoring template: manifest, module, schema, fake ports, tests, receipt,
  canary and rollback. `src/agents/template/`, `test/agents/template.test.ts`, `docs/agent-authoring.md`.
- [x] M14.4 Publish operator runbooks and incident/reconcile/restore procedures. `docs/runbooks/README.md` + purge runbook.
- [x] M14.5 Verify every milestone has receipt, reviewer, artifact hash, limitations and rollback result.
  `pnpm milestone:audit` → M0–M13 VERIFIED; mỗi milestone có receipt `docs/execution/receipts/M<N>-2026-09-28*.json`
  (PostgreSQL thật, rollback `scripts/rehearse-rollback.mjs` PASS). Receipt M13.2/M13.3 dùng định dạng cũ, chỉ là tham khảo.
- [x] M14.6 Run complete local gate suite and archive final compatibility matrix. Receipt
  `docs/execution/receipts/M14-2026-09-27T16-51-45-542Z.json` (14 commands PASS, PostgreSQL 17.10, 0 skipped);
  matrix `docs/execution/compatibility-matrix.json`, audit `docs/execution/milestone-audit.json`.
- [x] M14.7 Human review architecture/security/recovery and explicitly approve release scope. Human owner duyệt
  2026-09-27 (kèm duyệt security đổi delegation sang manifest grant `agents.delegate`, bỏ hard-code `orchestrator`).

**PASS:** a new agent team can onboard without extra undocumented milestone; all contracts, tests,
runbooks and rollback paths exist; unresolved blockers are explicit rather than hidden.

## 14. Checklist điều kiện hoàn tất toàn dự án

- [ ] Contract package versioned, generated, documented và independently testable.
- [ ] Agent mới không import host private code và chạy parity qua in-process/process/container.
- [ ] Registry/policy/grant/model/tool/memory/sandbox checks ở execution boundary.
- [ ] Run/attempt/step/wait/checkpoint/event/outbox/receipt durable, idempotent và recoverable.
- [ ] Collaboration typed, bounded, auditable, cycle-safe và không hard-code orchestrator.
- [ ] Memory scoped, revisioned, provenance-aware, retention/export/delete-safe và untrusted in prompt.
- [ ] Artifact/evidence verify hash/length/owner; `unknown` không biến thành success.
- [ ] Session/compaction deterministic, gap-safe, branch-safe và budget-aware.
- [ ] API/UI/MCP/A2A (nếu bật) versioned, authorized, reconnectable và backward-compatible.
- [ ] Security, observability, backup/restore, capacity, load/soak và incident runbooks có evidence.
- [ ] Migration/canary/disable/rollback đã diễn tập; run cũ không bị thay semantics.
- [ ] Docs không còn claim vượt code; mọi NOT_RUN/BLOCKED có owner và điều kiện mở khóa.

## 15. Change control và nguyên tắc cho model triển khai

1. Đọc mốc hiện tại, dependencies và file ownership trước khi sửa.
2. Một commit/PR chỉ làm một mốc logic; không trộn refactor không liên quan.
3. Không xóa compatibility path trước khi consumer matrix và rollback window PASS.
4. Không đánh dấu PASS cho mocked-only, skipped, TODO, terminal process exit hoặc observer hint.
5. Khi external effect không xác minh được, giữ `unknown`, tạo reconcile task và dừng retry mù.
6. Khi contract cần đổi, cập nhật schema, generated types, tất cả consumers, tests, docs và migration
   trong cùng change request; ghi trade-off và rollback.
7. Cuối mỗi mốc chạy gate phù hợp, tạo receipt, cập nhật `PROGRESS.md`, rồi mới bắt đầu mốc sau.
8. Chỉ human owner mới phê duyệt secrets, cloud apply, production activation và release scope.
