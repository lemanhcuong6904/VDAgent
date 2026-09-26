# VDaAgent Platform Refactor Plan

## 0. Mục tiêu

Nâng Team 6 cAi từ modular monolith chạy workflow trong API process thành một agent platform có
thể mở rộng theo số lượng model, agent, tool, warehouse, workflow, tenant và worker; tự host được
bằng Docker Compose; có tracing, logging, metrics, recovery và đường nâng cấp lên nhiều replicas.

Kế hoạch này giữ PiRuntime làm execution runtime/model adapter trong giai đoạn đầu. Python là
ngôn ngữ first-class cho team agent qua `agent-runner.v1`, process/container boundary và SDK Python;
team Python không import backend TypeScript, database client hoặc Pi tables. Python/LangGraph chỉ là
lựa chọn ở lớp orchestration/graph khi có lợi ích rõ ràng; không viết lại runtime đang quản lý Pi
session, tool authorization và persistence nếu chưa có contract tương đương và test parity.

Nguyên tắc bất biến:

- PostgreSQL là source of truth cho tenant scope, task, run, invocation, event, outbox, session,
  memory, artifact, lease và usage metadata.
- Không dùng process-local memory làm trạng thái cuối cùng của task, lease, cancellation hay event.
- Agent/tool chạy theo manifest, capability và policy server-side. Prompt không phải security
  boundary.
- PiRuntime là runtime/adapter có thể thay thế, không chứa business workflow.
- Sandbox là provider contract; Docker là adapter self-host mặc định, không để public API tùy ý
  proxy Docker socket.
- Mọi workflow có idempotency, deadline, retry, cancellation và recovery behavior.
- Telemetry mặc định không chứa prompt, row data, secrets hoặc nội dung memory.

### 0.1. Trả lời trực tiếp các yêu cầu nền tảng

| Yêu cầu | Quyết định trong platform | Điều kiện để gọi là hoàn tất |
| --- | --- | --- |
| Nhiều data warehouse | `WarehouseAdapter` + `WarehouseCatalog` + canonical query/artifact contract; mỗi nguồn là package adapter độc lập. | Ít nhất hai adapter production-like chạy qua cùng conformance suite, có policy, credential reference, dialect, cancellation và bounded result. |
| Nhiều workflow | `WorkflowSpec`/registry và typed DAG; workflow template chỉ là prior, không phải router cố định. | Câu hỏi mới tạo được `PlanSpec` hợp lệ, có thể bỏ/thêm/lặp step, replan hoặc yêu cầu clarification khi thiếu dữ liệu. |
| Chỉ cấp warehouse và câu hỏi | Planner thực hiện discover -> ground -> plan -> execute -> validate -> synthesize; model chỉ đề xuất plan, server kiểm tra plan. | Planner chọn source/agent/tool theo capability, schema, policy và budget; không dùng keyword/table hard-code làm security boundary. |
| Team agent độc lập backend | Agent TypeScript hoặc Python chỉ dùng SDK và versioned `agent-runner.v1`; không import server/web/database private API. | Plugin chạy process/container boundary, crash hoặc dependency conflict không làm API core chết; JSONL/HTTP bridge có version và compatibility test. |
| Agent nói chuyện với agent | `agents.catalog`, `delegate`, `send`, `wait`, `result` và artifact references; mọi edge đều qua policy. | Parent/child run, trace, quota, depth/fan-out, payload limit và durable delivery được kiểm chứng; không có direct unrestricted mesh. |
| Thêm agent không ảnh hưởng core | Registry version, validation, quarantine, canary, tenant feature flag, promote/rollback/disable. | Thêm package + manifest + tests không sửa route/core schema; agent lỗi có thể rollback độc lập và run cũ giữ audit/output. |

Đây là boundary bắt buộc của thiết kế. Code hiện tại đã có contract, capability catalog, heuristic
planner, model profile, telemetry, ledger, local session auth, event cursor replay và worker sandbox
boundary. Những phần này chưa chứng minh được worker kill/recovery, OIDC provisioning, model-backed
planning parity, backup/load evidence hay multi-warehouse production conformance. Vì vậy không đánh
dấu platform-ready trước khi các gate ở phần 9-12 có bằng chứng test và vận hành.

## 1. Baseline hiện tại

### Cần giữ

- TypeScript/Hono API, React/Vite frontend, MCP SDK và PostgreSQL migrations.
- AgentPlugin, AgentPool, McpToolPool, schema/authorization/timeout/output limit.
- PiRuntime với Pi Agent Core, provider/model adapter, session lease, context pruning và tool loop.
- Durable memory theo (space_id, user_id, agent_id) và Pi session theo scope.
- Dataset, chart, report artifact có owner scope.
- SandboxProvider contract và Docker sandbox adapter.
- Invocation tree, cancellation, artifact links và workflow E2E test.
- Docker Compose self-host flow và governance trong GIT_RULE.md.

### Đã triển khai trong baseline refactor hiện tại

- AgentPool có manifest/capability validation, ModelRegistry, WorkflowRegistry và planner typed
  proposal với server-side validation; heuristic chỉ còn compatibility fallback.
- Web task được ghi cùng `platform_runs`, worker claim bằng lease/fencing/heartbeat, outbox có
  claim/retry, usage được ghi, và event cursor được lưu để SSE replay.
- Web session bearer mode, secure secret validation, body limit, secure headers, CORS, per-process
  rate limit, `/ready`, `/metrics` và audit denial events đã có implementation local.
- API không còn mount Docker socket; worker dùng `SandboxSupervisor` để giới hạn concurrency và
  timeout. Agent Python/external chạy qua `agent-runner.v1` JSONL và SDK Python.

### Giới hạn còn phải kiểm chứng hoặc hoàn thiện

- OIDC/session gateway, key rotation và tenant provisioning là external prerequisite; demo mode
  không được dùng cho public deployment.
- Distributed rate limiting, backup/PITR restore, migration rollback/forward và load/capacity
  benchmark chưa được diễn tập trên môi trường mục tiêu.
- Worker kill/recovery trước và sau side effect, DB outage, duplicate delivery/idempotency và
  rolling deploy chưa có integration evidence đầy đủ.
- Hai warehouse adapter production-like chưa chạy cùng một conformance suite có credential/policy;
  plugin quarantine/canary/rollback và CI denylist import vẫn là target của P1.
- PiRuntime internal service boundary, LangGraph/Langfuse integration và output parity đầy đủ chưa
  được chứng minh; planner model-backed hiện có deterministic fallback.
- OTel exporter delivery, dashboard/alert validation, sandbox provider conformance và admission
  control cần test/vận hành thực tế trước khi gọi platform-ready.

## 2. Kiến trúc đích

~~~text
Client / MCP / Operator
          |
          v
API Gateway / Hono (stateless)
  auth, rate limit, request validation, task creation, read APIs, SSE transport
          |
          +--> PostgreSQL
          |      tenant, run ledger, task, invocation, event, outbox,
          |      session, memory, artifact, usage, audit
          |
          +--> Workflow Planner / Graph Runtime
          |      capability discovery, graph definition, typed state,
          |      retries, approvals, child runs
          |
          +--> Agent Registry / SDK
          |      versioned manifests, package validation, canary, rollback
          |
          +--> Durable Worker Pool
          |      claim lease, heartbeat, fence, execute, retry, reconcile
          |                 |
          |                 +--> AgentRunner protocol
          |                 |      isolated team agent process/container
          |                 |
          |                 +--> PiRuntime service/adapter
          |                 |      model call, Pi session, tool loop
          |                 |
          |                 +--> Tool Gateway / MCP ToolPool
          |                 |      authorization, schema, timeout, quota
          |                 |
          |                 +--> Sandbox Supervisor
          |                        Docker now; gVisor/Kata/OpenSandbox later
          |
          +--> Event Delivery
                 PostgreSQL cursor/source of truth -> SSE/WebSocket/pub-sub wake-up

Telemetry: OpenTelemetry -> Collector -> Prometheus/Grafana + structured logs
LLM traces: Langfuse adapter, optional and content-redacted
~~~

Python/LangGraph là lựa chọn cho Workflow Planner / Graph Runtime, không phải điều kiện để đổi
toàn bộ platform. Một node LangGraph gọi PiRuntime qua internal HTTP/gRPC hoặc adapter cùng contract.
Python team agent dùng `agent-runner.v1` JSONL process bridge; host thực thi tool call qua ToolPool
và chỉ truyền scope/grant đã kiểm tra. PiRuntime tiếp tục sở hữu model/tool loop, session lease và
ToolPool trong giai đoạn chuyển tiếp.

LangChain chỉ dùng khi cần chuẩn hóa nhiều provider/model, structured output hoặc fallback. Không
bọc một agent loop thứ hai quanh PiRuntime. Langfuse làm LLM trace/prompt version/eval; OpenTelemetry
là lớp telemetry chung cho HTTP, worker, DB, tool, sandbox và runtime.

## 3. Contract platform

### 3.1 Agent manifest

Mở rộng AgentPlugin descriptor hoặc tạo schema version mới:

~~~text
AgentManifest:
  apiVersion, id, version, name, description
  capabilities, requiredCapabilities
  inputSchema, outputSchema
  tools/tool grants, modelProfile, guardrails
  limits: maxDepth, maxParallelChildren, maxToolCalls,
         maxDurationMs, maxTokens
~~~

Planner hỏi registry:

- agent nào có capability yêu cầu;
- input/output schema và version nào tương thích;
- tool grant, model profile, budget và tenant policy nào được phép;
- workflow nào yêu cầu node nào.

agents.delegate chuyển từ enum data/compare/... sang delegation tới agent được resolve từ
capability, nhưng vẫn giữ allowlist, depth, budget và parent/child scope server-side.

### 3.2 Model registry

Tách provider/model khỏi agent code:

~~~text
ModelProfile:
  id, provider, model, api_key_ref, capabilities
  context_limit, max_output_tokens, timeout, retry_policy, cost metadata
~~~

PiRuntime nhận modelProfile nhưng chỉ server-side config mới resolve secret. Registry phải hỗ trợ:

- nhiều provider/model cho cùng agent;
- routing theo capability, latency, cost hoặc task type;
- fallback có giới hạn;
- model/prompt version để audit;
- fake deterministic model cho test.

Thêm model chỉ cần provider adapter/profile và contract test, không sửa workflow graph.

### 3.3 Tool contract

Giữ McpToolPool làm policy enforcement point. Mọi tool phải có typed input/output schema,
capability/agent grant, authorize(scope), timeout, cancellation, output byte limit, mutability,
quota class, audit metadata và idempotency behavior nếu có side effect.

Không cấp agents: ["*"] cho tool nhạy cảm nếu không có policy riêng. alwaysAvailable chỉ dành cho
primitive được review. tools/list và Pi phải trả đúng giao của manifest, tenant policy và runtime
grants.

### 3.4 PiRuntime protocol

Chuẩn hóa contract có version:

~~~text
PromptRequest:
  run_id, trace_id, tenant scope, agent_id, model_profile
  system, prompt, session_id, tool grants, deadline, cancellation

PromptResult:
  output, usage, model, tool_calls, session_revision
  artifacts, status, error classification
~~~

PiRuntime phải stateless ngoài session lease/persistence; worker mới sở hữu lifecycle run. Python/
LangGraph gọi protocol này, không truy cập trực tiếp Pi session/ToolPool tables.

### 3.5 Workflow/graph contract

Workflow đăng ký như module versioned:

~~~text
WorkflowSpec:
  id, version, trigger schema, required capabilities
  state schema, graph definition, retry/deadline policy
  approval points, output schema, artifact policy
~~~

Graph node chỉ nhận typed state và scope; node không tự đổi tenant identity. Child run, artifact và
event đều có parent run, idempotency key và trace context.

### 3.6 Multi-warehouse contract

Warehouse không được mô hình hóa như một mock table provider duy nhất. Tạo `WarehouseAdapter` và
`WarehouseCatalog` provider-neutral với các capability sau:

- `list_sources`, `list_databases`, `list_schemas`, `list_tables`;
- `describe_relation`, `sample`, `profile`, `explain`;
- `query` với parameterized query, dialect/capability metadata và bounded result;
- `persist_dataset` qua artifact store;
- optional: semantic metrics, lineage, freshness, access policy và async query job.

Mỗi adapter tự chịu trách nhiệm dialect, pagination, cancellation, credential reference, connection
pool và error classification. Core chỉ nhận canonical schema, `DataSourceRef`, `QueryRequest` và
`QueryResult`; agent không import SDK của Snowflake/BigQuery/Databricks/Postgres trực tiếp.

Warehouse registry phải hỗ trợ nhiều adapter cùng lúc, chọn nguồn theo tenant/policy/capability,
và có catalog cache với version/freshness. Credentials chỉ là secret reference trong server-side
configuration. Dữ liệu, dataset và query đều gắn `space_id`, `user_id`, `warehouse_id` và policy.

Mục tiêu onboarding warehouse: thêm một package adapter + manifest + contract/conformance tests +
secret config; không sửa API, worker, planner hoặc agent core. Bộ adapter đầu tiên phải có mock,
Postgres-compatible và ít nhất một warehouse cloud qua cùng conformance suite.

### 3.7 Dynamic planner, không phụ thuộc một workflow cố định

Với input tối thiểu là warehouse access và câu hỏi tự nhiên, planner phải tự thực hiện:

~~~text
discover -> ground schema/data -> propose typed plan -> execute bounded DAG
         -> validate evidence -> replan on recoverable error -> synthesize answer/artifacts
~~~

Planner không được dựa vào `if prompt contains ...` hoặc chuỗi cố định `data -> compare -> ...`.
Workflow template chỉ là prior/optimization; planner được phép bỏ node, thêm node, lặp truy vấn,
đổi agent theo capability, yêu cầu clarification/approval hoặc dừng khi bằng chứng không đủ.

Mỗi plan được persist thành `PlanSpec`/`PlanStep` với:

- mục tiêu, assumptions, required capabilities và source selection;
- typed input/output schema cho từng step;
- dependency DAG, deadline, retry/replan policy và budget;
- evidence/artifact requirements và acceptance checks;
- parent run, trace context và idempotency key.

Planner chỉ được chọn agent/tool từ registry và policy giao cho tenant. Model có thể đề xuất plan,
nhưng server phải validate capability, schema, scope, cost, depth, fan-out và side-effect policy
trước khi execute. Nếu không tìm được capability hoặc data evidence, hệ thống trả thiếu năng lực/
thiếu dữ liệu rõ ràng thay vì bịa hoặc rơi vào workflow mặc định.

Implementation transition: planner heuristic đang có chỉ được dùng làm compatibility fallback cho
workflow cũ và test deterministic. P2 phải thay đường đi chính bằng model-backed typed planning hoặc
graph planner tương đương, với schema validation, capability resolution, bounded retries, evidence
checks và deterministic fallback khi model lỗi. Không được gọi fallback heuristic là dynamic planning
đã hoàn tất.

### 3.8 Agent team SDK và isolation

Team agent không được import `src/server.ts`, `src/web-api.ts`, database client hoặc implementation
nội bộ. Cung cấp package `agent-platform-sdk` cho TypeScript và SDK Python tương đương qua
`agent-runner.v1` chỉ gồm:

- manifest/descriptor và schema helpers;
- `RuntimeClient`, `ToolClient`, `WarehouseClient`, `ArtifactClient`, `AgentClient` ports;
- typed event, cancellation, deadline, trace context và error classes;
- local fake clients cho unit test.

Python bridge là contract bắt buộc, không phải integration tùy chọn:

- Host gửi `run` và `cancel`, nhận `result`, `event` hoặc `tool_call` theo JSONL, có `protocol`,
  `request_id`, `call_id`, scope, deadline và version.
- Python SDK cung cấp `AgentManifest`, `AgentContext`, `ToolClient`, `WarehouseClient`,
  `ArtifactClient` và `AgentClient`; tool call quay lại host để authorization/quota/trace.
- Manifest Python được đăng ký bằng `AGENT_EXTERNAL_MANIFESTS`; command/args chạy process riêng,
  không nhận database/provider secret từ host.
- Mọi thay đổi protocol phải có contract test chạy cùng Python reference agent và TypeScript host;
  incompatible version phải bị quarantine, không tự fallback vào backend internals.

Agent package chạy theo ba mức isolation:

1. In-process chỉ dành cho code platform đã tin cậy và local development.
2. Worker/process riêng là mặc định cho team plugin; crash, memory leak hoặc dependency conflict
   không làm API process chết.
3. Container/sandbox riêng dành cho plugin hoặc code chưa được tin cậy; chỉ nhận capability grants,
   không nhận database credential.

Backend core giao tiếp với agent qua versioned `AgentRunner` protocol. Agent chỉ nhìn thấy scope,
tools và artifacts được cấp; không tự mở connection tới warehouse, Postgres hay Docker.

### 3.9 Agent-to-agent communication tools

Cung cấp các tool nền tảng có policy, thay vì cho agent gọi implementation của agent khác:

- `agents.catalog`: tìm agent theo capability, version, health và policy;
- `agents.delegate`: tạo child run với typed input/output;
- `agents.send`: gửi message/event có correlation và delivery status;
- `agents.wait`: chờ child run hoặc approval;
- `agents.result`: đọc output/evidence đã persist;
- `artifacts.read/write`: trao đổi dataset/report/chart reference, không nhồi payload tùy ý.

Agent nào nói chuyện với agent nào được quyết định bởi capability grant + tenant policy + workflow
policy. Không mở unrestricted mesh: luôn kiểm tra scope, allowed edges, max depth, max fan-out,
deadline, token/cost budget, payload size và side-effect class. Giao tiếp async phải qua durable run
event/outbox; giao tiếp sync chỉ là optimization.

### 3.10 Safe agent onboarding

Đăng ký agent là một pipeline, không phải import module trực tiếp vào backend:

1. Đọc manifest và kiểm tra API/schema version, ID/namespace, capability, tool grant, model profile,
   resource limit và declared data access.
2. Chạy static validation, dependency/license/secret scan và contract/conformance tests bằng fake
   runtime/warehouse.
3. Kiểm tra không import private backend modules, không khai báo capability/tool vượt policy, không
   có namespace collision và không tạo migration không được review.
4. Đưa package vào registry versioned ở trạng thái `pending`; chạy health check và canary run.
5. Bật bằng feature flag/tenant allowlist; theo dõi error, latency, cost và authorization denial.
6. Promote hoặc rollback bằng registry snapshot; backend core không cần rebuild để vô hiệu agent lỗi.

Agent plugin không được tự đăng ký route, middleware, database table, secret hoặc process signal.
Các thay đổi cần platform boundary mới phải qua ADR/PR của CORE.

### 3.11 North-star acceptance scenarios

- Cấp thêm warehouse adapter mới: registry/catalog nhận nguồn, planner query được bằng canonical
  tools, không sửa backend core.
- Đặt câu hỏi chưa từng có workflow template: planner tạo plan DAG, chọn agent theo capability,
  persist evidence và trả lời hoặc nêu thiếu dữ liệu.
- Thêm agent team mới: chỉ thêm SDK package + manifest + tools + tests; API vẫn start và agent cũ
  không thay đổi.
- Một agent bị timeout/crash: run/step kết thúc theo policy, worker khác có thể retry/reconcile,
  API và agent khác vẫn hoạt động.
- Hai agent trao đổi: chỉ qua `agents.*`/artifact tools, có parent/child trace, policy decision,
  quota và durable result.
- Disable/rollback agent: run mới không chọn agent đó, run cũ giữ output/audit; không cần rollback
  backend schema hoặc restart toàn bộ platform.

## 4. Durable runtime ledger và worker

Đây là phần cốt lõi lấy từ pattern grok-bot và phải triển khai trước horizontal scale.

### 4.1 Bảng/khái niệm bắt buộc

- runs: run_id, tenant scope, workflow version, status, deadline, attempt, usage, terminal reason.
- run_steps/invocations: parent/child tree, node/agent/tool, input/output references, status,
  attempt, lease, usage và error class.
- run_events: sequence tăng dần theo run/tenant, payload metadata đã redact.
- outbox_events: event ghi cùng transaction với state transition.
- worker_leases: owner, expiry, heartbeat và fencing token.
- idempotency_keys: request/job/side-effect key và kết quả đã commit.
- usage_records: model/tool tokens, latency, cost estimate và provider metadata.

### 4.2 Worker lifecycle

~~~text
queued -> leased -> running -> waiting -> completed
                         |-> retryable -> queued
                         |-> failed
                         |-> cancelled
~~~

Worker claim bằng transaction và FOR UPDATE SKIP LOCKED; không giữ transaction trong lúc gọi model
hoặc tool. Worker phải heartbeat, tôn trọng deadline/cancellation, retry theo error class, reject
stale worker commit bằng fencing token, reconcile lease hết hạn và ghi terminal state đúng một lần.

API restart không làm mất run. Run được reclaim sau lease expiry hoặc reconciler đánh dấu failure
có lý do.

### 4.3 Transactional outbox và event cursor

Tạo task hoặc đổi state phải ghi state row và outbox event trong cùng transaction. Publisher chỉ
gửi sau commit; lỗi publish không làm mất state.

SSE đọc theo run_id/user_id/cursor từ durable event store. Reconnect tiếp tục từ cursor; in-memory
queue chỉ là optimization. Redis/NATS nếu có chỉ làm wake-up/pub-sub, không thay PostgreSQL.

## 5. Observability

### 5.1 Correlation context

Mọi log/trace/span có request_id, trace_id, span_id, tenant/space hash, task_id, run_id,
invocation_id, parent_invocation_id, agent_id, workflow version, worker_id và attempt.

Không dùng raw user_id, prompt, query result, memory text hoặc token làm metric label.

### 5.2 OpenTelemetry

Instrument HTTP ingress/egress; planner/graph node; PiRuntime model request/stream/usage; MCP
tool authorization/timeout/output; PostgreSQL query category/pool wait; worker lease/heartbeat/
retry/fence; sandbox lifecycle; outbox publish và event delivery.

Telemetry opt-in/exporter-neutral. Không có collector vẫn chạy bình thường.

### 5.3 Metrics

- API rate, error rate, p50/p95/p99 latency.
- Queue depth, oldest job age, lease age, heartbeat miss, retry và stale worker reject.
- Run duration, active runs, terminal outcomes, cancellation latency.
- Model latency, provider error/rate limit, tokens, estimated cost, fallback count.
- Tool latency/error/timeout/output bytes và authorization denial.
- DB pool wait, query/lock latency, connections, WAL/size/index health.
- Memory search latency/hit/bytes/quota saturation.
- Sandbox startup/exec latency, active containers và resource failures.
- SSE clients, reconnects, cursor lag và event publish failures.

### 5.4 Logs, Langfuse và dashboards

Structured JSON logs với redaction ở logger boundary và leak test. Langfuse trace model/prompt/
tool/evaluation bằng trace_id/run_id chung; không mặc định ghi toàn bộ prompt production.

Compose profile observability gồm OTel Collector, Prometheus, Grafana; Loki chỉ thêm khi logs nhiều
process không đủ cho điều tra. Dashboard/alert cho queue age, error rate, provider outage, DB pool,
orphaned run, stale lease, sandbox failure và cost budget.

## 6. Security và tenant isolation

Trước public deployment bắt buộc:

- OIDC/session thật cho web; bỏ X-User-Id làm credential.
- Auth thống nhất cho /api, /v1, /mcp, SSE và artifact routes.
- Enforce space/user/agent ở mọi query và artifact; cross-tenant negative tests.
- Token agent bắt buộc Bearer, constant-time compare, rotation và reject placeholder lúc startup.
- Rate limit theo tenant/IP/route; body, field, nesting, prompt, output và upload limits.
- CSRF/CORS/secure headers/TLS ở reverse proxy.
- Audit log cho authorization denial, artifact access, model/tool execution và admin changes.
- Model output, memory và tool result là untrusted data.

Sandbox phải tách Docker control vào SandboxSupervisor; API public không mount Docker socket.
Container non-root, read-only rootfs, egress policy, drop capabilities, resource quota, timeout
kill, workspace expiry/cleanup. Không truyền credential host vào sandbox.

## 7. Storage, memory và artifacts

- PostgreSQL giữ metadata, ledger, event, session, memory và artifact nhỏ.
- Memory scope cố định (space_id, user_id, agent_id), có quota, retention, forget, audit và bounded
  FTS; vector search chỉ thêm sau retrieval benchmark.
- Pi session, long-term memory, run transcript và artifact là bốn mục đích khác nhau.
- Artifact lớn dùng ArtifactStore adapter local filesystem/S3-compatible; PostgreSQL giữ owner,
  checksum, MIME/type, size, version và reference.
- Read artifact phải verify ownership; final answer chỉ trỏ artifact đã persist và verify trực tiếp.
- Backup encryption, PITR/restore rehearsal, migration lock, retention và disk alert là release gate.

## 8. Deployment và scale

### Compose profiles

- core: API, PostgreSQL, worker, frontend.
- observability: OTel Collector, Prometheus, Grafana, optional log backend.
- sandbox-runtime: supervisor và Docker adapter.
- python-orchestrator: chỉ bật khi dùng LangGraph; gọi PiRuntime protocol nội bộ.

Mỗi profile có health/readiness, graceful shutdown, resource limits, persistent volume, backup/
restore guide và secret injection. Không để secret trong image hoặc .env committed.

### Đường scale

1. Một API + worker + PostgreSQL, đo baseline.
2. Nhiều worker replicas với lease/fencing, API stateless.
3. Nhiều API replicas sau khi event/cancel/active run không còn process-local.
4. Tách sandbox supervisor khi cần boundary bảo mật hoặc scale độc lập.
5. Thêm Redis/NATS chỉ sau benchmark và outage/replay test.
6. Chỉ cân nhắc Kubernetes/gVisor/Kata/OpenSandbox khi tải/threat model chứng minh.

## 9. Lộ trình

### P0 — Baseline và CI xanh

- Sửa test manifest và Biome hiện tại.
- Fake model, fake warehouse, deterministic clock, test database riêng.
- Load scenario greeting/chat/analytics/delegation/sandbox.
- Chốt SLO, model budget, tenant limit và migration policy.

Done: typecheck, lint, unit/integration/frontend build xanh trong CI.

### P1 — Registry và capability

- Tạo CapabilityRegistry, ModelRegistry, WorkflowRegistry, schema version và manifest validator.
- Tạo WarehouseRegistry/WarehouseCatalog và canonical warehouse/tool contract; thêm conformance
  suite cho nhiều adapter.
- Tạo agent-platform-sdk với ports, fake clients và versioned AgentRunner protocol.
- Bỏ orchestrator hard-code specialist IDs/keyword routing; thêm `agents.catalog` và capability
  resolution.
- Thêm model profile/fallback/cost policy vào PiRuntime request.
- Thêm plugin validation/quarantine/canary/rollback; giữ backward-compatible adapter cho
  AgentPlugin v1.

Done: thêm model/agent/tool/warehouse bằng package + manifest/config, không sửa core orchestrator,
API route hoặc database implementation.

### P2 — PiRuntime protocol và optional Python/LangGraph

- Đóng gói PiRuntime thành internal service/adapter protocol.
- Tạo dynamic planner: discover catalog, tạo PlanSpec/DAG, validate capability/schema/budget rồi
  execute; template chỉ là optimization.
- LangGraph node (nếu bật) gọi PiRuntime; typed state, plan version và step state được persist.
- Python agent bridge `agent-runner.v1` chạy được bằng reference SDK, không truy cập trực tiếp Pi
  tables/ToolPool; LangGraph chỉ gọi các protocol public tương tự.
- Cài agent communication tools (`catalog`, `delegate`, `send`, `wait`, `result`) với policy edges.
- Thêm Langfuse adapter và trace correlation.

Done: câu hỏi không có template vẫn tạo được plan hợp lệ hoặc giải thích thiếu capability/data;
analytics graph chạy qua PiRuntime, Python reference agent gọi được warehouse/tool qua bridge, output
parity với workflow cũ, trace đầy đủ và rollback được về workflow TypeScript.

### P3 — Ledger, worker và recovery

- Thêm runs, run_steps, run_events, outbox_events, worker_leases, idempotency_keys và usage_records.
- Worker claim SKIP LOCKED, lease, heartbeat, fencing, retry và reconciler.
- Di chuyển runTask/planner/delegation/agent execution ra worker; API chỉ enqueue và đọc.
- Persist event cursor; SSE reconnect/replay.

Done: kill API/worker ở mọi điểm không làm mất hoặc duplicate side effect; stale worker không commit;
cancel từ replica khác hoạt động.

### P4 — Observability và security

- OTel spans/metrics/log redaction, dashboards và alerts.
- OIDC/session auth, rate limit, secret validation/rotation, CORS/CSRF/TLS.
- Artifact ownership verification, input-limit alignment, output sanitization và audit events.

Done: trace điều tra được run; security negative tests pass; không leak secret/content; backup restore
đã diễn tập.

### P5 — Sandbox và capacity

- Tách Docker control, quota/cleanup/expiry, provider conformance suite.
- Load test worker/API/DB/sandbox, đặt capacity limit và admission control.
- Chỉ sau benchmark mới chọn Redis/NATS hoặc runtime sandbox khác.

Done: sandbox không có host control path; capacity/degradation được đo; rolling deploy không mất
run/event.

### 9.1. Snapshot trạng thái và bằng chứng (2026-09-26)

Bảng dưới đây phân biệt implementation local với bằng chứng production. `Partial` không có nghĩa là
phase đã hoàn tất; phase chỉ được chuyển sang `Done` khi các điều kiện ở cột cuối có test hoặc receipt
vận hành có thể lặp lại.

| Phase | Trạng thái hiện tại | Bằng chứng trong repository | Còn thiếu để hoàn tất phase |
| --- | --- | --- | --- |
| P0 Baseline/CI | `Done (local + integration smoke)` | `pnpm check`, `pnpm lint`, `pnpm test`, frontend build; unit tests runtime/security/warehouse; `agent-memory` và `analytics-e2e` pass trên database tạm riêng của Compose. | Workload baseline có giới hạn chi phí và SLO vẫn chưa được đo. |
| P1 Registry/capability | `Partial` | `src/registry.ts`, `src/model-registry.ts`, `src/workflow.ts`, `src/warehouse-contract.ts`, `src/agent-sdk.ts`, `src/agent-runner.ts`; tests registry/planner/warehouse/runner. | Hai adapter production-like cùng conformance suite; quarantine/canary/rollback và CI kiểm import private API. |
| P2 PiRuntime/Python planner | `Partial` | `src/planner.ts` validate `plan.v1`; `src/agents/analytics.ts` model proposal + fallback; `sdk/python`; A2A tools và runner tests. | Internal Pi protocol service, LangGraph/Langfuse integration, full output parity và restart/cancel contract test. |
| P3 Ledger/worker/recovery | `Partial` | Migrations `006`-`010`; `src/run-ledger.ts`, `src/run-worker.ts`, `src/outbox.ts`, `db/migrations/009_web_event_cursor.sql`; unit tests worker/outbox/SSE cursor code. | PostgreSQL integration test kill/reclaim, stale fence, duplicate side effect, DB restart và rolling deploy. |
| P4 Observability/security | `Partial` | `src/web-auth.ts`, `src/agent-auth.ts`, `src/rate-limit.ts`, `src/audit.ts`, `src/metrics.ts`, secure middleware; migrations `011`; `docs/operations.md`, `docs/security.md`. | OIDC gateway, distributed limiter, backup/restore drill, OTel exporter/dashboard/alert validation và external threat review. |
| P5 Sandbox/capacity | `Partial` | Worker-only Docker socket trong Compose, `src/sandbox-supervisor.ts`, Docker quotas, resource limits và observability profile. | Load/capacity benchmark, admission/degradation policy, provider conformance, cleanup under failure và rolling-deploy evidence. |

Các lệnh local chỉ chứng minh code/contract hiện chạy; chúng không thay thế database restore, load,
identity-provider, exporter hoặc cloud warehouse evidence. Vì vậy snapshot này không đánh dấu
platform-ready.

## 10. Test và release gates

### Contract/unit

- Manifest/schema compatibility và output validation.
- Model routing/fallback/timeout/cost.
- Tool authorization, scope, schema, timeout, cancellation, output limit.
- Workflow transition, graph routing, depth/parallel/budget.
- Artifact ownership, memory isolation/quota/retention, session CAS/lease.

### Integration/recovery

- Migration idempotency và database restore.
- Worker crash trước/sau model call, lease expiry, duplicate delivery, stale fence commit.
- API restart, rolling deploy, DB restart, outbox retry, event replay và SSE reconnect.
- Provider timeout/rate limit/invalid output; sandbox timeout/kill/cleanup/host isolation.
- Cross-tenant read/write negative tests.

### Release gate

- Format/lint/typecheck/unit/integration/frontend build xanh.
- Security/dependency/secret/license scan xanh.
- Load baseline trong budget/SLO.
- Migration rollback/forward compatibility được review.
- Dashboard/alert/runbook/backup restore đã kiểm tra.
- PR đúng branch/team ownership trong GIT_RULE.md.

## 11. Ownership

- CORE: runtime protocol, registry, worker/lease/fence, database lifecycle, CI.
- AGENT_A: agent manifest, capability planner, LangGraph adapter, prompt/model policy.
- AGENT_B: tool/MCP authorization, memory, artifact ownership và contract tests.
- DATA: warehouse provider, dataset/artifact storage, query quota và data isolation.
- PRODUCT: API/UI task state, event cursor/SSE, auth UX và user-facing errors.
- Platform/SRE: OpenTelemetry, metrics/logs, Compose profiles, deployment, backup và alerts.

Mỗi phase tách thành PR nhỏ theo ownership; không merge toàn bộ migration runtime trong một PR.

### 11.1. Quy tắc thay đổi không làm gãy backend lõi

- Agent/warehouse/workflow package chỉ được phụ thuộc contract package và SDK public; import nội bộ
  bị CI denylist kiểm tra.
- Registry load lỗi phải quarantine package và giữ API/worker core khởi động với các package hợp lệ.
- Manifest, schema, capability và tool grant phải được validate trước khi package nhận traffic.
- Migration core, route, auth middleware, lease protocol và tenant tables không được agent package tự
  sửa; thay đổi boundary cần ADR/PR của CORE.
- Mọi rollout agent mới qua pending -> canary -> tenant allowlist -> promote; rollback phải chỉ ra
  registry version và không xóa output/audit của run đã hoàn tất.
- Compatibility test phải chạy cả in-process fake runtime và AgentRunner process/container path;
  in-process chỉ là test/development mode, không phải isolation production.

## 12. Tiêu chí platform-ready

Chỉ gọi platform production-ready khi:

- Thêm model/agent/tool/warehouse/workflow không cần sửa orchestrator core, API route hoặc backend
  database implementation.
- Có ít nhất hai warehouse adapter production-like chạy qua cùng catalog/query/artifact contract;
  planner chọn nguồn theo capability, policy và schema thay vì table/keyword hard-code.
- Câu hỏi ngoài workflow template được planner biến thành PlanSpec/DAG có bounded execution,
  replan/clarification và evidence validation.
- Agent team chỉ phụ thuộc agent-platform-sdk; plugin crash/dependency conflict không làm API core
  chết và plugin có canary/rollback/disable độc lập.
- Python agent chạy qua `agent-runner.v1` reference bridge, tool calls bị host authorize, protocol
  compatibility/restart/cancel test pass và không có direct database/backend import.
- Agent-to-agent communication chỉ qua typed tools/policy edges, có durable parent/child run và
  trace; không có unrestricted direct imports hoặc database access.
- PiRuntime/runtime adapter có protocol version, typed result, usage và trace context.
- API stateless; worker durable; task/event/cancel/retry survive restart và rolling deploy.
- Lease/fencing/idempotency/outbox/event cursor có negative và recovery tests.
- Tenant auth/authorization enforce ở web, operator, MCP, SSE và artifact.
- Sandbox có boundary, quota, cleanup và host/cross-tenant isolation test.
- Trace một request đến model/tool/DB/sandbox; logs redact; metrics có dashboard/alert.
- Backup restore, migration, load, outage và rollback đã diễn tập.
- Self-host Compose chạy đầy đủ core; cloud/broker/sandbox nâng cao là adapter tùy chọn.

Đây là kế hoạch refactor, không phải tuyên bố các năng lực trên đã tồn tại. Mỗi phase chỉ hoàn
thành sau khi có code, migration, test, telemetry evidence và tài liệu vận hành tương ứng.

## 13. Tài liệu và pattern nguồn

Plan này tổng hợp các tài liệu đang có trong repository:

- `docs/architecture.md`: boundary hiện tại, dữ liệu, scale limit, metrics và deployment direction.
- `docs/agents.md`: AgentPlugin, manifest, guardrail, session và agent test contract.
- `docs/tools.md`: MCP ToolPool, grants, schema, authorization, timeout và sandbox/tool scope.
- `docs/api.md`: HTTP/MCP contract, user scope, event và artifact API.
- `docs/agent-runner.md`: versioned JSONL bridge và process isolation cho agent ngoài process.
- `docs/operations.md`: startup, worker/outbox, secret, backup và recovery runbook.
- `docs/security.md`: auth, rate limit, audit và sandbox boundary.
- `docs/bug-check-2026-09-25.md`: findings về auth, lifecycle, concurrency, sandbox, input limit,
  sanitizer, frontend và environment.
- `docs/research-adoption-plan.md`: các pattern đã chắt lọc từ Pi ecosystem, OpenSandbox, agentbox,
  substrate và grok-bot; đặc biệt runtime ledger, lease/fence, outbox/event cursor, idempotency,
  recovery test và telemetry boundary.
- `outsources/REPO.md`: danh sách repository tham khảo; chỉ lấy pattern đã kiểm chứng, không chép
  nguyên subsystem hoặc coi roadmap của upstream là năng lực production.
- `GIT_RULE.md`: ownership, branch protection, PR, CI, secret handling và release gate.

Mọi quyết định thay đổi stack, schema hoặc boundary phải ghi thành ADR/PR riêng, nêu lý do, tác động,
rollback và bằng chứng benchmark. Không coi việc thêm LangChain, LangGraph, Langfuse, Redis,
Kubernetes hoặc sandbox runtime mới là mục tiêu tự thân; chỉ đưa vào khi contract, threat model,
capacity evidence và recovery test chứng minh giá trị.
