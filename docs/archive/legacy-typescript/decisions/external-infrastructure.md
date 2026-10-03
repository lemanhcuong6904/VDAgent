# Decision: External infrastructure adoption thresholds (M13.7)

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

## Hiện trạng (2026-09-27)

Platform hiện tại chạy trên PostgreSQL + Node.js với 2 process (API + worker), không có external
dependency ngoài database. Kiến trúc này đơn giản, dễ deploy, dễ debug, và đủ cho giai đoạn đầu.

**Các thành phần hiện tại:**

- **Agent orchestration**: spawn subagent trong process (fork qua `Agent` tool hoặc multi-agent
  workflow script). Không có workflow engine riêng.
- **Event transport**: SSE từ PostgreSQL `web_events` table, outbox pattern cho webhook/integration.
  Không có message broker.
- **Memory/search**: PostgreSQL full-text search (`ts_vector`) + embedding vector trong `jsonb`.
  Không có vector database chuyên dụng.
- **Architecture**: monolith có API và worker trong cùng codebase, chạy 2 process riêng biệt, share
  database pool.

## Framework: khi nào adopt external infrastructure?

Mỗi công nghệ external mang lại capability mới nhưng đổi lại là **complexity cost**: thêm
deployment dependency, monitoring, failure mode, version compatibility, network partition handling.
Chỉ adopt khi evidence chứng minh platform đã chạm ceiling của approach hiện tại và cost/benefit rõ ràng.

### Workflow engine (Temporal, Cadence, AWS Step Functions)

**Capability hiện tại:** spawn agent bằng `Agent` tool (session-local) hoặc `Workflow` tool
(background fan-out với pipeline/parallel). Workflow script là JavaScript, chạy trong Node.js VM,
không có durable execution (crash = mất state). Coordinator là single process.

**Ngưỡng adopt:**

1. **Workflow > 30 phút** và cần survive coordinator restart → durable execution.
2. **Fan-out > 100 agent** trong 1 workflow → distributed coordinator, sharding.
3. **Cross-region orchestration** (agent chạy ở nhiều cloud region) → geo-distributed coordinator.
4. **Compliance yêu cầu audit trail** của mọi decision step → built-in history + replay.

**Evidence cần thu thập:**

- Histogram thời gian workflow thực tế (p50/p95/p99/max).
- Tần suất crash coordinator và số workflow bị mất state.
- Số lượng agent tối đa trong 1 workflow (từ production traffic hoặc benchmark).

**Quyết định hiện tại:** **KHÔNG ADOPT**. Workflow hiện tại < 5 phút, fan-out < 20 agent (theo
`capacity-bench.ts` và PLAN.md guideline là "medium" ~10 agents). Coordinator crash hiếm (graceful
shutdown đã implement M13.1) và user có thể retry workflow thủ công nếu cần. Cost của Temporal/Step
Functions (infra + learning curve + migration effort) không xứng đáng lúc này.

**Future trigger:** nếu production data cho thấy 10% workflow > 15 phút hoặc coordinator crash làm
mất > 5 workflow/tuần → reassess.

---

### Message broker (NATS, RabbitMQ, Kafka)

**Capability hiện tại:** SSE stream events từ PostgreSQL (`web_events` table), polling mỗi 1s.
Outbox pattern (`platform_outbox_events`) deliver webhook/integration events với at-least-once
guarantee. Worker claim runs từ `platform_runs` table với advisory lock.

**Ngưỡng adopt:**

1. **Event fanout > 1000 subscriber** cho 1 event type → pub/sub với topic, không phải PostgreSQL scan.
2. **Event rate > 10k/s** → PostgreSQL write bottleneck, cần broker với partition.
3. **Cross-service communication** giữa nhiều microservice (không phải API + worker) → service mesh,
   event bus.
4. **Event replay** từ arbitrary timestamp → log-based broker (Kafka), không phải table scan.

**Evidence cần thu thập:**

- Event write rate (events/s) từ production hoặc stress test.
- Số concurrent SSE subscriber và bandwidth tiêu thụ.
- Query latency của `EventTail.next()` khi table có > 1M rows.

**Quyết định hiện tại:** **KHÔNG ADOPT**. Event rate thấp (< 100/s theo ước lượng từ capacity bench:
200 runs tạo ra ~600 events, throughput ~20 runs/s → ~60 events/s). SSE chỉ 1-1 (user ↔ browser),
không phải fanout. PostgreSQL handle được event write ở volume này. Outbox đủ cho webhook delivery.

**Future trigger:** nếu production traffic đạt > 5k events/s hoặc SSE query p95 > 200ms với event
table > 10M rows → adopt NATS Jetstream (lightweight, dễ deploy hơn Kafka).

---

### Vector database (Pinecone, Weaviate, Qdrant, pgvector extension)

**Capability hiện tại:** embedding vector lưu trong `agent_memory_entries.embedding` (jsonb array).
Search bằng cosine similarity computed in PostgreSQL:

```sql
SELECT text,
       1 - (embedding <=> $1::vector) AS similarity
FROM agent_memory_entries
WHERE user_id = $2 AND space_id = $3
ORDER BY embedding <=> $1::vector
LIMIT 10
```

Yêu cầu `pgvector` extension (đã cài trong migration). Index: `ivfflat` hoặc `hnsw`.

**Ngưỡng adopt external vector DB:**

1. **Embedding dimension > 3072** (pgvector giới hạn 2000 trong một số version) → Pinecone/Weaviate.
2. **Memory entries > 10M per workspace** và search latency > 500ms p95 → sharded vector index.
3. **Hybrid search** (vector + metadata filter phức tạp) mà PostgreSQL query planner không tối ưu được.
4. **Multi-modal embedding** (text + image + audio) → vector DB có metadata schema linh hoạt hơn.

**Evidence cần thu thập:**

- Memory entry count phân bố (p50/p95/p99 per workspace).
- Search latency với dataset > 100k entries (chạy benchmark seed 100k row, measure query time).
- Embedding dimension thực tế (hiện tại dùng model nào? OpenAI ada-002 là 1536-dim).

**Quyết định hiện tại:** **KHÔNG ADOPT external DB; SỬ DỤNG pgvector**. PostgreSQL với pgvector
extension đủ cho < 1M entries/workspace. Embedding dimension 1536 (ada-002) hoặc 3072 (ada-003) đều
trong giới hạn. Query latency chấp nhận được với HNSW index. Không cần infra thêm.

**Future trigger:** nếu search p95 > 300ms với production data hoặc cần dimension > 3072 → migrate
sang Qdrant (self-hosted, open source, dễ migrate từ pgvector).

---

### Graph database (Neo4j, Amazon Neptune)

**Capability hiện tại:** KHÔNG CÓ graph query. Relationship giữa runs (parent/child), artifacts
(owner_run_id), memory (tags) đều lưu trong relational schema. Không có graph traversal.

**Ngưỡng adopt:**

1. **Knowledge graph** với entity relationship phức tạp (> 3 level nested query) → Cypher/Gremlin query.
2. **Agent reasoning** yêu cầu graph traversal (ví dụ: tìm shortest path giữa 2 entity) → graph algorithm.
3. **Multi-hop question answering** (RAG với graph context) → graph vector search.

**Evidence cần thu thập:**

- User feedback yêu cầu graph reasoning (ví dụ: "how is X related to Y?").
- Query complexity của relational schema (có query nào > 5 JOIN không?).

**Quyết định hiện tại:** **KHÔNG ADOPT**. Không có use case graph query. Agent workflow là tree
(parent-child), không phải arbitrary graph. Relational schema đủ. Graph DB là overkill.

**Future trigger:** nếu product roadmap bổ sung knowledge graph feature hoặc multi-hop reasoning →
reassess (có thể dùng Neo4j community edition self-hosted).

---

### Microservices split

**Capability hiện tại:** monolith với API và worker trong cùng codebase, deploy 2 process riêng biệt:

- **API process**: HTTP server (Hono), `/api/v1/*`, `/api/events`, readiness/liveness probe.
- **Worker process**: `DurableRunWorker` claim runs từ queue, execute agent, ghi result.

Cả 2 process share cùng database pool, cùng migration, cùng schema. Code reuse cao (RunLedger,
ArtifactStorage, McpToolPool).

**Ngưỡng split thành microservices:**

1. **Team > 10 engineer** và merge conflict thường xuyên → split codebase theo bounded context.
2. **Scaling requirement khác nhau**: API cần scale nhanh (stateless), worker cần scale chậm (stateful
   lease) → deploy riêng với resource limit khác nhau. *(Hiện tại đã làm được: Docker Compose scale
   `api` và `worker` độc lập.)*
3. **Technology heterogeneity**: một service cần ngôn ngữ khác (ví dụ: Python cho ML inference) →
   service riêng với contract qua gRPC/HTTP.
4. **Failure isolation**: bug trong agent execution không được crash API server → process boundary
   (đã có) hoặc network boundary (microservice).

**Evidence cần thu thập:**

- Team size và velocity (merge/deploy frequency, conflict rate).
- Resource usage difference (API vs worker CPU/memory profile từ Prometheus).
- Crash correlation (API crash có làm worker crash không? vice versa?).

**Quyết định hiện tại:** **KHÔNG SPLIT thêm**. Monolith với 2 process là sweet spot: đủ failure
isolation (worker crash không ảnh hưởng API), đủ independent scaling, nhưng vẫn share code và
migration. Team nhỏ (< 5 người theo dự án học), split thành microservice chỉ tăng complexity
(service discovery, distributed tracing, network latency, deployment coordination) mà không có lợi ích rõ.

**Future trigger:** nếu team > 8 người và có ít nhất 2 squad làm feature độc lập → split theo
bounded context (ví dụ: AgentRuntime service, ArtifactStorage service, Observability service).

---

## Tóm tắt quyết định

| Infrastructure       | Decision     | Lý do                                                                 |
|----------------------|--------------|-----------------------------------------------------------------------|
| Workflow engine      | Không adopt  | Workflow < 5 phút, fan-out < 20, coordinator ổn định                  |
| Message broker       | Không adopt  | Event rate < 100/s, SSE 1-1, PostgreSQL đủ                            |
| Vector DB (external) | Không adopt  | pgvector extension đủ, < 1M entries/workspace                         |
| Graph DB             | Không adopt  | Không có use case graph query                                         |
| Microservices split  | Không split  | Monolith 2-process đủ isolation + scaling, team nhỏ                   |

**Nguyên tắc chung:** adopt external infrastructure khi có **quantitative evidence** từ production
(hoặc realistic benchmark) chứng minh current approach đã chạm ceiling, VÀ benefit rõ ràng > cost.
Không adopt dựa trên "best practice" hay "industry standard" nếu chưa cần.

## Lộ trình monitor

Để phát hiện khi nào chạm ngưỡng, cần track metrics:

1. **Workflow**: duration histogram, fan-out count, coordinator crash rate.
2. **Events**: write rate (events/s), SSE query p95 latency, outbox backlog size.
3. **Memory search**: entry count per workspace, search p95 latency, embedding dimension.
4. **Scaling**: API/worker CPU/memory usage, request rate, queue depth.

Metrics này đã có trong Prometheus (M12) hoặc có thể tính từ `platform_*` tables. Review quarterly.
