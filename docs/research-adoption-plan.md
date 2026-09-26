# Research adoption record

This document captures design patterns and adoption decisions; it is not a production readiness
certificate. Current implementation evidence and remaining gates are tracked in [PLAN.md](../PLAN.md)
section 9.1. Historical recommendations remain useful only when they agree with the versioned
contracts and tests in the current branch.

# Kế hoạch học hỏi và nâng cấp nền tảng agent

Tài liệu này chắt lọc các ý tưởng phù hợp từ `oh-my-pi`, `pi-subagents`, `rakazo-new`,
`substrate`, `OpenSandbox`, `agentbox` và `grok-bot`. Mục tiêu là làm Team 6 cAi ổn định hơn,
dễ tự host và có thể scale theo số liệu, không thay stack hiện tại hoặc đưa nguyên dự án khác vào.

## Quyết định nền tảng

- Giữ TypeScript, Node.js, Hono, Pi Agent Core, React/Vite, MCP SDK và PostgreSQL.
- Giữ modular monolith cho API, agent registry và tool pool; agent không cần process hay database
  riêng.
- PostgreSQL tiếp tục là nguồn sự thật cho user/space scope, task, invocation, Pi session, memory,
  event và artifact nhỏ.
- Hạ tầng phải chạy được local/self-host bằng Docker Compose. AWS và hosted providers là adapter
  tùy chọn, không phải dependency của core.
- Ưu tiên PostgreSQL job leases trước Redis/SQS; thêm dịch vụ mới chỉ khi benchmark hoặc yêu cầu
  vận hành chỉ ra lợi ích rõ ràng.
- Giữ dữ liệu model, prompt, output và nội dung memory ngoài metrics/log mặc định. Telemetry chỉ
  được ghi nội dung khi người vận hành bật rõ ràng.

## Bài học từ các dự án

| Dự án | Ý tưởng đáng tiếp thu | Giới hạn khi áp dụng vào Team 6 cAi |
| --- | --- | --- |
| `oh-my-pi` | Pi agent loop có telemetry OpenTelemetry tùy chọn; memory có scope/backend riêng, giới hạn phần recall đưa vào context và hỗ trợ FTS trước khi cần embeddings. Session/artifact có ranh giới lưu trữ riêng. | Không thay Pi Agent Core bằng coding-agent CLI. Giữ PostgreSQL làm memory backend production; SQLite/file backend chỉ phù hợp local single-node hoặc export. |
| `pi-subagents` | Child run có trạng thái, event, output, usage/cost, timeout, cancel, steer và kết quả typed; background work có thể quan sát và phục hồi. | Không lấy artifacts JSONL trên local disk làm nguồn sự thật của web service nhiều process. Persist lifecycle vào PostgreSQL, JSONL chỉ dùng cho export/debug. |
| `rakazo-new` | Tách contract khỏi provider adapter; Docker/none/fake sandbox kiểm tra qua cùng contract; Pi là runtime adapter có thể thay thế. | Lấy boundary và test pattern, không chép lại mono-repo nhiều package hay các provider không cần. |
| `substrate` | Actor/worker separation, lease, capacity, warm pool và suspend/resume có thể giảm chi phí khi workload thưa nhưng nhiều actor. | Kubernetes, CRD, gVisor/microVM, controller và worker pool là một nền tảng vận hành lớn. Chỉ nghiên cứu sau khi có tải đủ lớn và benchmark cho thấy compute idle là chi phí chính. |
| `OpenSandbox` | Sandbox có lifecycle API, runtime adapter, lease/expiry, egress policy và lựa chọn runtime bảo mật. Ranh giới API/control plane với nơi thực thi sandbox là quan trọng. | Không triển khai full control plane/Kubernetes ngay. Trước mắt tách Docker control khỏi API và giữ Docker làm adapter self-host mặc định. |
| `agentbox` | Local-first Docker, provider contract, trạng thái file ghi atomic/có lock, recover sau restart, checkpoint và không chuyển credential host vào sandbox. | AgentBox là môi trường coding agent một máy; không bê nguyên nested Docker daemon, FUSE hoặc quyền `SYS_ADMIN` sang service multi-user. |
| `grok-bot` | Runtime ledger, worker lease/fence, outbox/event cursor, tenant-scoped persistence, idempotency và negative/recovery tests được thiết kế thành contract trước khi deploy. | Đây là codebase Python/React và kế hoạch lớn hơn scope hiện tại; chỉ lấy pattern, không đổi ngôn ngữ hoặc chép các subsystem đang còn kế hoạch/chưa được chứng nhận production. |

## Stack tự host mục tiêu

```text
Nginx (TLS, proxy, body limits)
        |
        +--> Hono API / static React client
                  |
                  +--> PostgreSQL: task, run, event, memory, session, metadata
                  +--> worker process: durable Pi/agent runs
                  +--> sandbox supervisor --> Docker containers

OpenTelemetry SDK --> OTel Collector --> Prometheus --> Grafana
                                  `--> optional log backend later
Redis: optional event wake-up/cache only, never durable job or memory store
```

Mọi thành phần trong sơ đồ có thể chạy local bằng Docker Compose. Nginx, Prometheus, Grafana,
OpenTelemetry Collector và Redis đều là OSS; chỉ bật profile quan sát hoặc Redis khi cần. Không đưa
Prometheus label có `userId`, `taskId`, `sessionId` hoặc dữ liệu tự do vì cardinality sẽ tăng nhanh.

## Các giai đoạn

### P0 — Chốt baseline và tiêu chí đo

**Trạng thái:** plan. Ghi lại benchmark hiện tại trước khi đổi runtime hoặc persistence.

- Tạo workload tổng hợp cho greeting, chat thường, analytics, delegation và sandbox command.
- Đo p50/p95/p99 API, thời gian run, số lượt model/tool, token/cost, DB pool wait, memory search,
  sandbox create/exec, RSS và dung lượng artifacts.
- Ghi rõ các giới hạn hiện tại: workflow cũ còn có đường chạy trong API process; cancellation
  wake-up vẫn in-memory; `/health` chỉ xác nhận API process; worker nội bộ mới giữ Docker socket.

**Xong khi:** có baseline có thể chạy lại bằng dữ liệu giả, cùng concurrency/cấu hình, không gọi
model hoặc warehouse thật nếu chưa chủ động cho phép.

### P1 — Quan sát được bằng OSS, ít rủi ro

- Thêm structured JSON logging với `request_id`, `task_id`, `invocation_id`, `agent_id`,
  `run_id` và `trace_id`; redact token, prompt và nội dung row.
- Dùng OpenTelemetry API/SDK theo kiểu opt-in; instrument HTTP, Pi model call, MCP tool, delegation,
  DB query và sandbox call. Khi không bật exporter, runtime vẫn hoạt động bình thường.
- Thêm `/metrics` với metric cardinality thấp: request count/latency, run outcomes/duration,
  tool errors/timeouts, active runs, worker lease age, DB pool wait và sandbox resource failures.
- Tạo Compose profile `observability` gồm OTel Collector, Prometheus và Grafana; dashboard có sẵn
  cho API, agent runs, DB, sandbox và token/cost. Mặc định retention ngắn; bảo vệ Grafana khỏi
  public access.
- Chỉ thêm Loki nếu Docker logs và structured logs không đủ để điều tra lỗi qua nhiều process.

**Xong khi:** trace của một test run nối được từ request đến model/tool/DB; test xác nhận telemetry
không chứa secret hoặc nội dung user; tắt telemetry không làm thay đổi kết quả workflow.

### P2 — Durable workflow trước scale API

- Tạo run/job lifecycle bền vững trong PostgreSQL: queued, leased, running, waiting, completed,
  failed, cancelled và retryable.
- Worker claim bằng transaction/`SKIP LOCKED`, lease expiry, heartbeat và monotonic fencing token;
  không giữ transaction mở trong lúc gọi model/tool.
- Ghi enqueue qua transactional outbox cùng transaction tạo task. Worker phải idempotent vì crash,
  retry và duplicate delivery đều có thể xảy ra.
- Persist event sequence/cursor để REST/SSE reconnect đọc tiếp từ PostgreSQL. SSE chỉ là transport,
  không là nguồn sự thật.
- Thêm restart tests: kill trước/sau model call, worker lease hết hạn, stale worker ghi kết quả,
  cancel ở replica khác, duplicate job và provider timeout.

**Xong khi:** API restart không làm task biến mất; stale worker không commit; mỗi task kết thúc ở
một trạng thái giải thích được; client reconnect không bỏ lỡ trạng thái cuối.

### P3 — Tách sandbox control plane khỏi API

- Tạo `SandboxProvider` contract và `SandboxSupervisor` riêng. API gửi lệnh có scope, quota, timeout
  và capability; supervisor chỉ cung cấp create/exec/stop/delete hẹp, không proxy Docker API tùy ý.
- Giữ Docker adapter self-host; network mặc định tắt, root filesystem read-only, user không đặc
  quyền, drop capabilities, giới hạn CPU/RAM/PID/thời gian/output và workspace riêng.
- Không để public-facing API mount Docker socket. Nếu vẫn cùng một host ở giai đoạn đầu, ghi rõ đó
  là trust boundary một máy và giới hạn người dùng; process riêng trên cùng host không thay thế
  sandbox kernel isolation.
- Benchmark gVisor và Kata qua cùng conformance suite. Chỉ chọn runtime cứng hơn nếu threat model
  yêu cầu chạy code không tin cậy và đo được cold start/resource overhead.
- Xem OpenSandbox làm tài liệu tham khảo cho lifecycle/egress API, không triển khai Kubernetes chỉ
  để có sandbox manager.

**Xong khi:** test xác nhận agent không thể truy cập Docker control API, host paths, metadata
service hoặc tenant workspace khác; worker restart/reconcile được sandbox không còn lease.

### P4 — Củng cố memory và artifacts

- Giữ scope memory `(space_id, user_id, agent_id)` trong PostgreSQL; bổ sung quota tổng theo user/
  space, retention/delete, audit và test chéo scope.
- Search FTS và bounded recall trước; chỉ thử vector embeddings khi bộ test retrieval chứng minh
  FTS không đủ. Embedding/model bổ sung phải opt-in và có giới hạn chi phí.
- Memory là gợi ý không đáng tin cậy, không phải system instruction; không nhét transcript đầy đủ
  vào prompt. Tách memory dài hạn, Pi session history và artifact theo mục đích.
- Artifact lớn chuyển sang filesystem/object-store adapter; metadata, owner, checksum và quyền đọc
  vẫn ở PostgreSQL. Local filesystem adapter để self-host; S3 chỉ là adapter tùy chọn.
- Dùng test cho retention, forget/delete, revision/CAS, quota, corruption và migration trước khi
  thay schema lưu Pi session hiện có.

**Xong khi:** restart không mất memory; dung lượng và retention có giới hạn; mọi artifact có thể
được kiểm tra ownership mà không cần đưa payload lớn vào DB query hoặc model context.

### P5 — Bounded multi-agent lifecycle

- Giữ Pi runtime chung và plugin agent như hiện tại; mở rộng descriptor với tool grants/capability,
  schema version và giới hạn run rõ ràng.
- Mỗi child invocation có typed input/output, parent/child ID, deadline, max depth, max parallel,
  token/tool budget, status, usage/cost và failure reason.
- Thêm status, cancel, retry, output inspection và run trace qua API; không cần agent process riêng.
- Tạo contract tests chung cho tool authorization, agent output, timeout, cancellation, retries,
  output truncation và prompt injection qua memory/tool results.

**Xong khi:** workflow analytics E2E có thể khôi phục trạng thái child sau worker restart và report
cuối cùng trỏ về dataset/chart/evidence đã persist.

### P6 — Redis chỉ khi có số liệu cần

- Ban đầu dùng PostgreSQL cho durable queue/event/cursor và PostgreSQL advisory locks như primitive
  cross-process; không tạo Redis queue song song.
- Nếu SSE wake-up hoặc cache tạo tải DB đo được, thêm Redis cho pub/sub/cache với PostgreSQL vẫn là
  nguồn sự thật. Mất Redis chỉ làm client polling chậm hơn, không mất task/event.
- Nếu sau này cần broker, dùng adapter queue; triển khai OSS như Redis Streams/NATS chỉ sau khi có
  durability, replay, consumer group và vận hành được kiểm chứng. Không giữ job quan trọng chỉ trong
  Redis Pub/Sub.

**Điều kiện vào phase:** benchmark cho thấy polling/cursor hiện tại là bottleneck; có dashboard,
load profile và test Redis outage/reconnect trước khi thêm service.

### P7 — Self-host release và hardening

- Cung cấp Compose profiles `core`, `observability`, `sandbox-runtime`; mặc định không bật mọi
  thành phần phụ.
- Nginx làm TLS reverse proxy; app bind private Docker network. Có thể thay Nginx bằng proxy khác
  mà không đổi core API.
- Thêm migration command riêng, graceful shutdown, readiness/liveness riêng, backup + restore
  rehearsal, disk/DB capacity alarms, resource quotas và retention controls.
- Trước khi mở public: thay `X-User-Id` bằng OIDC/session thật, enforce authorization mọi API/SSE/
  artifact, rate limit và threat review sandbox. Không tuyên bố production-ready khi chưa có crash,
  backup restore và tenant-isolation evidence.
- Giữ cloud-specific adapters tách biệt. Mọi workflow developer/test chạy được bằng Compose và
  fake model/warehouse, không yêu cầu AWS account.

## Không làm ở các phase đầu

- Không đổi TypeScript sang Python chỉ vì `grok-bot` dùng Python.
- Không database riêng cho từng agent/user; không bắt buộc hosted memory/vector service.
- Không Redis làm memory store hoặc nguồn duy nhất của task/event.
- Không microservice cho từng agent/tool; không Kubernetes/EKS, Substrate worker pool hoặc full
  OpenSandbox control plane trước khi có benchmark chứng minh nhu cầu.
- Không bật prompt/content capture trong logs/traces mặc định.
- Không dùng process-local map làm trạng thái cuối cùng của task, cancellation, lease hoặc SSE event.

## Tài liệu nguồn đã rà soát

- `oh-my-pi`: `docs/memory.md`, `docs/mnemosyne-memory-backend.md`, `docs/blob-artifact-architecture.md`,
  `packages/agent/src/telemetry.ts`.
- `pi-subagents`: `docs/observability.md`, run lifecycle, background runner và recovery tests.
- `rakazo-new`: Pi runtime adapter, Docker/none sandbox adapters và sandbox conformance tests.
- `substrate`: README, worker-pool/sandbox configuration, OpenTelemetry/Prometheus manifests.
- `OpenSandbox`: README, secure-container-runtime OSEP, sandbox lifecycle/runtime implementation.
- `agentbox`: `docs/architecture.md`, Docker provider, durable local registry, recovery/checkpoint flow.
- `grok-bot`: `IMPLEMENT.md`, PostgreSQL runtime repository/worker, outbox/event cursor và threat/data
  handling decisions. Các receipts cũng đánh dấu rõ những integration/deployment/recovery gates còn
  chưa hoàn tất; plan này chỉ tiếp thu pattern, không coi toàn bộ roadmap là năng lực đã kiểm chứng.

Các phase là thứ tự đề xuất, không phải cam kết rằng phần nào đã được triển khai. Mọi thay đổi
runtime cần có issue/PR riêng, migration/backward-compatibility review, tests offline và cập nhật
architecture sau khi được xác minh.
