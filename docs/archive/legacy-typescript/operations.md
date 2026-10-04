# Vận hành platform

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

## Khởi động

`docker compose up --build -d` chạy API, worker và PostgreSQL. API phục vụ tại `127.0.0.1:3000`;
API và worker chạy dưới UID không phải root với filesystem chỉ đọc. Production Compose đặt
`SANDBOX_PROVIDER=none` và không mount Docker socket, vì quyền vào socket tương đương quyền quản trị
Docker trên host. Docker sandbox là tùy chọn cho deployment riêng có supervisor tin cậy; khi đó phải
mount socket có chủ ý và đặt `DOCKER_GID` bằng group ID của socket (`stat -c %g /var/run/docker.sock`).

Compose đặt `NODE_ENV=production`; roster Python mặc định chạy qua Bubblewrap với namespace riêng,
filesystem image chỉ đọc, network riêng và child seccomp filter. Chạy local development trực tiếp
trên host với `NODE_ENV=development` khi cần bỏ launcher.

Readiness kiểm tra PostgreSQL:

```sh
curl -fsS http://localhost:3000/health
curl -fsS http://localhost:3000/ready
```

Bật các dịch vụ telemetry tùy chọn khi cần điều tra hoặc thử nghiệm tích hợp:

```sh
docker compose --profile observability up -d
```

Prometheus đọc `/metrics`; Grafana ở `http://localhost:3001`; OTel Collector mở receiver OTLP ở
cổng 4317/4318. Core hiện vẫn xuất metrics Prometheus và structured logs local; OTLP exporter,
dashboard provisioning và alert rules chưa được cấu hình/kiểm chứng tự động, nên Collector không
phải dependency bắt buộc của core.

## Worker và outbox

Worker claim `platform_runs` bằng `FOR UPDATE SKIP LOCKED`, heartbeat lease và fencing token. Outbox
publisher claim `platform_outbox_events` bằng lease riêng, dispatch sau commit, đánh dấu `published_at`
sau khi thành công và tăng `attempts` khi sink lỗi. Không xóa outbox để sửa lỗi; inspect `attempts`,
`last_error`, `claimed_until` rồi chạy lại publisher.

Publisher gửi mỗi event qua `createOutboxFanout` (`src/outbox-consumers.ts`). Mặc định chỉ có consumer ghi
log một dòng JSON ra stdout. Mỗi consumer nhận một event đúng một lần; nếu consumer lỗi, event vào
dead-letter của consumer đó chứ không chặn consumer khác. Một event lỗi 10 lần (`maxAttempts`) thì
publisher không claim nữa; xem runbook [outbox-lag](runbooks/outbox-lag.md) trước khi reset `attempts`.

Các run có thể xem theo `platform_runs`, `platform_run_events`, `platform_run_steps` và
`platform_usage_records`. Usage record có `metadata.cache_read_tokens`/`cache_write_tokens` (đã tính
trong `input_tokens`). Nếu cost luôn bằng 0, tìm dòng `usage.record_failed` trên stderr của worker. Không đọc prompt hoặc row data từ logs/metrics để điều tra; dùng artifact
đã ownership-check trong API.

## Auth và secrets

Local dùng `WEB_AUTH_MODE=demo`, trong đó UI giữ compatibility với `X-User-Id`. Public deployment
phải dùng `WEB_AUTH_MODE=session` và `WEB_AUTH_SECRET` ngẫu nhiên dài; client gửi
`Authorization: Bearer <vdagent.v1...>` cho `/api`, artifact và SSE. Operator `/v1` vẫn dùng
`API_TOKEN`, còn MCP dùng `AGENT_TOKEN_<ID>`. Token web session được ký HMAC, có expiry tối đa 30
ngày; identity provider/OIDC gateway chịu trách nhiệm provision `web_users` và cấp token cho subject
tương ứng.

Đặt `PLATFORM_REQUIRE_SECURE_SECRETS=true` hoặc `NODE_ENV=production` để startup từ chối
`API_TOKEN`/`AGENT_TOKEN_*` ngắn hoặc placeholder. Không đặt secret trong image, `.env` committed,
telemetry, prompt hay artifact.

## Tracing (OTLP / Langfuse)

Mặc định không bật gì — `TELEMETRY_MODE`/`METRICS_ENABLED` như cũ. Đặt một trong hai nhóm biến
sau để `src/otel-tracing.ts` export span thật qua OTLP/HTTP (thay cho `Telemetry` JSON/no-op):

- OTLP trực tiếp: `OTEL_EXPORTER_OTLP_ENDPOINT` (base, tự thêm `/v1/traces`) hoặc
  `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (full path), cộng `OTEL_EXPORTER_OTLP_HEADERS` dạng
  `key=value,key2=value2` nếu receiver cần header auth.
- Langfuse: chỉ cần `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — endpoint
  `{LANGFUSE_HOST}/api/public/otel/v1/traces` và header `Authorization: Basic ...` được suy ra tự
  động từ public/secret key.

`OTEL_SERVICE_NAME`/`OTEL_SERVICE_VERSION` gắn vào resource attributes, `OTEL_TRACES_SAMPLER_ARG`
(0..1) chỉnh tỉ lệ sample root span. Span `agent.model` trong `PiRuntime` mang thuộc tính
`gen_ai.*` theo OTel GenAI semantic conventions (operation, agent id, conversation id, provider,
model, usage tokens/cost) — không export nội dung prompt/completion.

Chạy local với stack `otel-collector` (`docker compose --profile observability up -d
otel-collector`): receiver OTLP trong `docker/otel-collector-config.yml` phải bind `0.0.0.0`, not
`localhost` — bind mặc định của image chỉ nghe loopback trong container nên port mapping
`127.0.0.1:4318:4318` của Docker sẽ không bao giờ chạm tới nó (export sẽ retry rồi timeout, không
có log lỗi rõ ràng ở collector). Đã sửa trong config; nếu đổi image/tự viết config khác thì giữ
nguyên `endpoint: 0.0.0.0:4317`/`0.0.0.0:4318` trong `receivers.otlp.protocols`.

Tracing được flush và dừng đúng thứ tự trong shutdown sequence của `server.ts`/`worker.ts` (bước
`tracing`, trước khi đóng `database`).

## Database và backup

Migrations chạy dưới PostgreSQL advisory lock và ghi vào `schema_migrations`. Trước khi nâng cấp:

1. Dump metadata và xác nhận backup mã hóa.
2. Chạy migration trên database clone.
3. Kiểm tra `/ready`, `platform_runs` chưa terminal và outbox pending.
4. Diễn tập restore/PITR trước khi promote production.

Không dùng `docker compose down -v` nếu chưa chủ ý xóa database local.

## Sự cố thường gặp

- `ready` trả `503`: kiểm tra PostgreSQL health, `DATABASE_URL` và migration lock.
- Queue tăng nhưng worker không claim: kiểm tra worker logs, `lease_until`, `worker_id` và
  `WORKER_CONCURRENCY`.
- Outbox `last_error` tăng: kiểm tra sink/exporter, không sửa trạng thái bằng tay trước khi giữ bản
  sao dữ liệu.
- Sandbox timeout: kiểm tra Docker daemon, `SANDBOX_MAX_TIMEOUT_MS`, quota và cleanup volume.
- 401/403: xác nhận bearer/session mode, token expiry, agent token theo đúng agent ID và audit event.

## Alerts và runbooks

`src/alerts.ts` đánh giá sáu tín hiệu vận hành trên ledger và lưu một row đang mở cho mỗi điều
kiện đang cháy vào `platform_alerts`. Alert chỉ có tính tư vấn: không đổi trạng thái run, không
cấp quyền cho hành động nào và không bao giờ chứa giá trị bí mật/PII khớp được.

```ts
const store = new AlertStore(pool);
await store.run();       // đánh giá + persist, an toàn khi gọi theo timer
await store.listOpen();  // alert đang mở, mới nhất trước
```

| Tín hiệu | Runbook |
| --- | --- |
| `stale_leases` | [stale-leases](runbooks/stale-leases.md) |
| `outbox_lag` | [outbox-lag](runbooks/outbox-lag.md) |
| `unknown_events` | [unknown-events](runbooks/unknown-events.md) |
| `cost_budget` | [cost-budget](runbooks/cost-budget.md) |
| `artifact_mismatch` | [artifact-mismatch](runbooks/artifact-mismatch.md) |
| `pii_leak` | [pii-leak](runbooks/pii-leak.md) |

Một fingerprint (ví dụ `stale_leases:critical`) chỉ có tối đa một row đang mở; lần quan sát lặp
lại tăng `occurrences`/`last_seen_at`, và điều kiện ngừng cháy thì tự resolve trong cùng giao dịch.
Worker chạy `AlertScheduler` mỗi `ALERT_EVAL_INTERVAL_MS` (mặc định 60000; `0` để tắt khi dùng cron ngoài).
Các lần chạy không chồng nhau; lỗi được log `alerts.evaluation_failed` và thử lại ở tick sau.

## Probes, startup order và shutdown (M13.1)

`/live` (alias `/health`) không kiểm dependency; `/ready` trả 503 khi đang start/drain, DB không
kết nối được, hoặc schema lệch build (`pending` = còn migration chưa chạy, `ahead` = DB có
migration build này không biết). Migration lấy advisory lock có timeout
(`MIGRATION_LOCK_TIMEOUT_MS`, mặc định 120s) và fail startup thay vì treo. SIGTERM: readiness
503 ngay → chờ `SHUTDOWN_DRAIN_DELAY_MS` → đóng HTTP (cắt SSE sau `HTTP_CLOSE_GRACE_MS`) → drain
worker (`WORKER_DRAIN_GRACE_MS`, run quá hạn trả về `retryable`) → outbox → pool, trong
`SHUTDOWN_TIMEOUT_MS`. Chi tiết: [runbooks/graceful-shutdown.md](runbooks/graceful-shutdown.md).

## Backup và restore (M13.2)

PostgreSQL là nguồn sự thật duy nhất, kể cả bytes artifact (`artifact_contents`), nên
`pg_dump --format=custom` là backup đầy đủ. Restore: dừng writer → kiểm checksum → restore vào DB
rỗng → một replica API, xem `/ready` (`schema: ahead` = image cũ hơn dump) → mở worker. Outbox là
at-least-once qua restore; consumer phải dedupe theo `outbox_id`. Effect xảy ra sau thời điểm dump
coi là `unknown`, phải reconcile trước khi chạy lại. Diễn tập:
`bash scripts/rehearse-backup-restore.sh`. Chi tiết: [runbooks/backup-restore.md](runbooks/backup-restore.md).

## Capacity baseline (M13.3)

`tsx scripts/capacity-bench.ts <url DB chứa "rehearsal"> [scale]` chạy đường code thật (Hono + v1
API, RunLedger, 4 × DurableRunWorker, McpToolPool, PostgresAgentMemoryProvider, ArtifactStorage)
trên DB dùng một lần. Model là **fake** (40 ms, 1.200 in / 300 out token); cost tính từ bảng giá
nêu trong receipt ($3/$15 mỗi 1M token), không đo từ provider. Một host (i5-12450H, 8 CPU,
PostgreSQL 17.10 container), hai lần chạy ổn định; receipt
`docs/execution/receipts/M13.3-capacity-bench.json`.

| Đường | Kết quả (p95) |
| --- | --- |
| API create run, c1 / c8 / c32 | 16 / 49 / 421 ms; 444 rps ở c8, **380 rps ở c32** |
| API read run, c8 | 13 ms |
| Worker: 20 parent × fan-out 8 = 160 run, 4 worker × 8 | ~105 run/s, 0 mất, 0 chạy trùng |
| Queue → start (160 run cùng lúc) | 1.1 s |
| Tool pool overhead (auth + schema + timeout) | 1.4–3.2 ms |
| Memory remember / search (500 entry) | 50 / 28 ms |
| Artifact store+readback 1 KB / 256 KB / 1 MB | 15 / 35 / 53 ms, 0 mismatch |
| Cost / run (fake profile) | $0.0081 |

Điểm bão hòa: create run lên c32 thì p95 tăng ~9× so với c8 và throughput *giảm*, nên ~8 request
ghi đồng thời mỗi replica là trần trên host này. Worker tốn ~270 ms overhead ledger mỗi run ngoài
40 ms model (claim `SKIP LOCKED`, 2 transition, heartbeat, usage). Chưa profile nguyên nhân; đây là
số đo, không phải cam kết production.

## Đo với model thật (`pnpm bench:e2e`)

Khác capacity bench ở trên (model giả), lệnh này dùng model thật từ `.env` (`MODEL_API_KEY`, không in ra log):
tạo PostgreSQL dùng một lần, chạy API và worker như 2 process riêng, gửi 3 kịch bản
(chào hỏi, liệt kê dữ liệu, phân tích có đáp án đúng) và ghi `docs/execution/live/e2e-benchmark-*.json`.

```sh
corepack pnpm bench:e2e --repeat 3 --budget 0.30
```

Lần đo 2026-09-28 (gpt-4o-mini): 9/9 PASS, tổng $0.0037; p50 2.7 s / 1.6 s / 6.4 s cho 3 kịch bản.
Kịch bản phân tích tốn 3 lượt gọi model, ~5.6k input token.

## Rollback rehearsal

`node scripts/rehearse-rollback.mjs` (cần `TEST_DATABASE_URL` dùng một lần) chứng minh có thể quay code
về baseline `b7bd273` mà không cần rollback database: migrate DB tới head hiện tại, xuất code baseline ra
thư mục tạm, chạy typecheck và test của baseline trên DB đó. Migration mới chỉ thêm bảng/cột nên code cũ
bỏ qua được. Không chứng minh rollback image hay restore dữ liệu (xem backup/restore ở trên).

## Transport/cache loss và rebuild từ PostgreSQL (M13.4)

Hệ thống không có Redis, NATS hay broker; PostgreSQL là nguồn sự thật duy nhất. Mọi state không
bền nằm trong process và được kiểm là dựng lại được:

| State trong process | Mất khi | Rebuild |
| --- | --- | --- |
| SSE fan-out `/api/events` (`subscriptions`) | restart, replica khác, worker process riêng | Stream đọc `web_events` sau cursor; publish local chỉ đánh thức sớm, poll (`eventPollMs`, 1s) phủ event do process khác ghi. Cửa sổ 2s đọc lại row commit trễ hơn id lớn hơn, dedupe theo id. |
| Stream v1 / A2A | như trên | Vốn đã poll `platform_run_events` / `a2a_tasks`. |
| `activeTasks` (AbortController) | restart | Cancel ghi `cancel_requested` vào DB; heartbeat của worker (mỗi max(1s, lease/3)) phát hiện và abort. |
| Lease worker | worker chết | Lease hết hạn → run được claim lại với fencing token mới (M13.2). |
| Rate limiter (`RateLimiter`, A2A per-client) | restart | Không rebuild: chỉ là bảo vệ, reset là chấp nhận được. N replica = N× limit. |
| Metrics (`metrics.ts`) | restart | Counter reset; Prometheus xử lý reset. Không phải source of truth. |

**Bug đã sửa:** trước đây `/api/events` chỉ phát event qua `subscriptions` của chính process. Với
compose mặc định (`api` + `worker` tách process), event do worker ghi chỉ tới browser khi client
reconnect. Giờ `web_events` là đường giao duy nhất.

## Security scan, SBOM và image pinning (M13.5)

`pnpm audit` / `npm audit` chạy định kỳ; kết quả hiện tại 0 lỗ hổng. SBOM 623 component trong
`docs/execution/dependency-bom.json`, license gate qua allowlist. Base image node/postgres pin
SHA256 digest, observability stack dùng tag semantic. Secret rotation: sinh mới, ghi `.env`,
restart. **Chưa có:** Trivy/Grype/OSV-Scanner độc lập; egress allowlist; sandbox escape test. Chi
tiết: [runbooks/security-scan.md](runbooks/security-scan.md).

## Canary deploy, rollback và kill-switch (M13.6)

Deploy version mới lên một replica trước, observe 10-15 phút (error rate, latency, queue depth).
Migration observation window: đợi 5 phút sau khi migration thành công trước khi scale up. Rollback:
nếu chỉ code bug thì deploy lại image cũ; nếu migration có lỗi thì restore từ backup hoặc viết
migration đảo ngược. Kill-switch: `SIGTERM` trigger graceful shutdown (drain delay → worker drain →
outbox stop → database close), grace period 40s; nếu không xong thì `SIGKILL`, run in-flight chuyển
`retryable`. Readiness probe `/ready` trả 503 khi drain để load balancer remove khỏi pool. Chi tiết
và smoke test: [runbooks/canary-rollback.md](runbooks/canary-rollback.md).

## External infrastructure adoption thresholds (M13.7)

Platform hiện tại không dùng external workflow engine, message broker, vector database riêng, graph
database hay microservices split. **Quyết định:** tiếp tục với PostgreSQL + Node.js monolith 2-process
(API + worker) cho đến khi có quantitative evidence chứng minh đã chạm ceiling. Ngưỡng cụ thể:
workflow > 30 phút, fan-out > 100 agent, event rate > 10k/s, memory search > 10M entries/workspace
với p95 > 300ms, hoặc team > 8 người. Chi tiết framework và monitor metrics:
[decisions/external-infrastructure.md](decisions/external-infrastructure.md).

## Quản lý version (`versions.json`)

`versions.json` là nguồn sự thật duy nhất cho version contract và thứ tự migration, giống alembic:
thứ tự lấy từ chuỗi `revision`/`downRevision`, không lấy từ tên file hay thư mục. Migration runner
(`src/database.ts` qua `src/migration-chain.ts`) từ chối branch, gap, cycle và revision trùng.

```sh
corepack pnpm versions list                          # contracts và chuỗi migration, head hiện tại
corepack pnpm versions check                         # registry khớp schemas/ và db/migrations/
corepack pnpm versions new-migration add_run_index   # tạo SQL mới nối vào head
corepack pnpm versions bump agent-scope "breaking: ..."  # tăng major $id, ghi lý do
```

Revision đã apply giữ nguyên id cũ (`001_...` tới `017_...`) để database hiện có không chạy lại.
Tên file không mang version (`schemas/agent-scope.schema.json`, `src/contracts/generated/agent-scope.ts`);
version nằm trong `$id` của schema và trong `versions.json`. Đổi contract thì sửa file tại chỗ và
`pnpm versions bump`, không tạo file `.v2` song song.
