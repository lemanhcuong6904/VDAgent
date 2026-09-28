# Runbook: canary deploy, migration window, rollback và kill-switch (M13.6)

## Canary deployment

Deploy version mới lên **một replica** trước, để load balancer route traffic tới cả version cũ và
mới. Observe metrics (error rate, latency p95/p99, queue depth, lease timeout) trong 10-15 phút.
Nếu không có anomaly, rolling update các replica còn lại.

**Docker Compose pattern** (local/staging):

```bash
# Replica hiện tại: team6-api, team6-worker
docker compose up -d --no-deps --scale api=2 --scale worker=2
# Observe logs, /ready endpoint, Prometheus metrics
docker compose logs -f --tail=50 api worker
# Nếu OK, stop container cũ và để replica mới chạy
docker compose up -d --no-deps --force-recreate api worker
```

**Kubernetes pattern** (production):

```yaml
# Deployment strategy: RollingUpdate với maxSurge=1, maxUnavailable=0
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      containers:
      - name: api
        image: team6/api:v1.2.3
        readinessProbe:
          httpGet:
            path: /ready
            port: 3000
          initialDelaySeconds: 5
          periodSeconds: 3
```

Rollout tự động tạo canary (1 pod mới), chờ readiness pass, sau đó terminate 1 pod cũ và tạo
tiếp pod mới. Pause giữa chừng: `kubectl rollout pause deployment/api`.

## Migration observation window

Sau khi **một replica** chạy migration thành công (migration lock giải phóng), **đợi ít nhất 5
phút** trước khi scale up các replica khác. Trong window này:

1. Kiểm tra log không có SQL error liên quan schema mới.
2. Kiểm tra `/ready` của replica đã migrate: `schema: ok`, không phải `pending` hay `ahead`.
3. Query thử vài endpoint đọc/ghi để verify schema change không break API contract.
4. Nếu phát hiện lỗi: rollback ngay (xem section dưới), không scale up thêm.

**Lý do:** migration có thể apply thành công nhưng query mới gây timeout hoặc lock contention.
Window này là cơ hội phát hiện trước khi toàn bộ fleet chạy code mới.

## Rollback procedure

### Trường hợp 1: Code có bug nhưng schema không đổi

**Rollback đơn giản:** deploy lại image/tag cũ, không cần database action. Canary sẽ dùng schema
hiện tại (forward-compatible).

```bash
docker compose pull  # Lấy tag cũ từ registry nếu đã xóa local
IMAGE_TAG=v1.2.2 docker compose up -d --force-recreate api worker
```

### Trường hợp 2: Migration có lỗi, cần revert schema

**Rollback cẩn thận:**

1. Stop toàn bộ API và worker (`docker compose stop` hoặc `kubectl scale --replicas=0`).
2. Restore từ backup gần nhất (xem [backup-restore](backup-restore.md)).
3. Sau khi restore xong, deploy code cũ (version trước migration), rồi start lại.

**Nếu không restore được:** viết migration đảo ngược thủ công, chạy trực tiếp qua `psql`. Ví dụ:

```sql
-- Migration 017 đã chạy: ALTER TABLE platform_runs ADD COLUMN priority INT DEFAULT 0
-- Rollback: DROP COLUMN và xóa entry trong schema_migrations
BEGIN;
ALTER TABLE platform_runs DROP COLUMN priority;
DELETE FROM schema_migrations WHERE version = '017_a2a_tasks';
COMMIT;
```

Sau đó deploy code cũ. **Chú ý:** forward compatibility bị phá vỡ nếu migration đã được production
dùng một thời gian (data đã tồn tại trong column mới). Restore từ backup an toàn hơn.

### Trường hợp 3: Rollback không được (breaking change đã commit)

Nếu migration đã chạy production > 24h và data mới đã được ghi (không thể rollback vì mất data),
chỉ còn cách **roll forward**: fix bug trong code hoặc schema, deploy version vá lỗi.

## Kill-switch và emergency stop

### Graceful shutdown

`SIGTERM` trigger ordered shutdown (đã implement M13.1): drain delay → worker drain → outbox stop →
database close. Grace period trong Docker: 40s (`stop_grace_period` trong `docker-compose.yml`).

```bash
docker compose stop api worker  # Gửi SIGTERM, chờ tối đa 40s
```

Kubernetes: `terminationGracePeriodSeconds: 40` trong pod spec.

### Force kill (SIGKILL)

Nếu graceful shutdown không hoàn thành trong grace period (worker bị stuck, deadlock, hoặc
migration lock không giải phóng), runtime sẽ gửi `SIGKILL`. **Hậu quả:**

- Worker đang xử lý run bị abort giữa chừng: run chuyển về `retryable` khi lease timeout.
- Outbox event chưa publish được sẽ publish lại sau khi restart (idempotent).
- Migration lock giải phóng khi connection đóng, replica khác có thể migrate.

**Emergency stop toàn bộ fleet:**

```bash
docker compose down  # Stop và remove container
# Hoặc trong Kubernetes:
kubectl scale deployment/api deployment/worker --replicas=0
```

### Kill-switch drill

**Mục đích:** verify graceful shutdown path hoạt động đúng và không mất run/event.

**Thực hiện:**

1. Seed 5 run vào queue, worker đang xử lý 2 run (concurrency=2), 3 run còn lại queued.
2. Gửi `SIGTERM` tới worker trong khi run đang execute.
3. Observe: worker reject claim mới, drain 2 run in-flight trong grace period (hoặc hand back nếu
   timeout), shutdown hoàn tất trước 40s.
4. Verify: sau khi restart, 3 run queued được claim và execute, 2 run đã finish không execute lại.

**Receipt:**

```json
{
  "drill": "kill-switch",
  "seed": { "queued": 5, "in_flight_at_signal": 2 },
  "shutdown": { "duration_ms": 1240, "handed_back": 0, "finished": 2 },
  "after_restart": { "executed_once": 5, "executed_twice": 0, "lost": 0 }
}
```

Đã implement trong `test/lifecycle.test.ts` section "worker drain". Để chạy drill thực tế:

```bash
# Terminal 1: start worker
docker compose up worker
# Terminal 2: seed runs, sau đó SIGTERM
docker compose exec worker kill -TERM 1
# Verify: check logs và database
```

## Readiness probe và traffic management

Load balancer (hoặc Kubernetes service) chỉ route traffic tới pod có `/ready` return 200. Khi pod
đang drain, endpoint trả về 503 → load balancer ngừng gửi request mới tới pod đó.

**Drain delay** (`DRAIN_DELAY_MS`, default 2s): sau khi nhận `SIGTERM`, đợi 2s trước khi bắt đầu
đóng HTTP server. Trong 2s này, load balancer có cơ hội detect `/ready` = 503 và remove khỏi pool,
tránh request mới gửi tới pod đang shutdown.

## Smoke test sau deploy

Sau mỗi lần deploy (canary hoặc full rollout), chạy smoke test:

```bash
# API health
curl -f http://localhost:3000/live && echo "liveness OK"
curl -f http://localhost:3000/ready && echo "readiness OK"

# Create + read run
RUN_ID=$(curl -s -X POST http://localhost:3000/api/v1/runs \
  -H "Authorization: Bearer $TOKEN" -H "X-Space-Id: smoke" \
  -H "Content-Type: application/json" \
  -d '{"workflow_id":"analytics","input":{},"idempotency_key":"smoke-'$(date +%s)'"}' \
  | jq -r .run_id)
curl -f http://localhost:3000/api/v1/runs/$RUN_ID -H "Authorization: Bearer $TOKEN" | jq .status

# SSE stream (expect heartbeat)
curl -N http://localhost:3000/api/events?user_id=smoke -H "Authorization: Bearer $TOKEN" &
sleep 3 && kill %1
```

Nếu bất kỳ bước nào fail → rollback ngay.
