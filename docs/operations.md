# Vận hành platform

## Khởi động

`docker compose up --build -d` chạy API, worker và PostgreSQL. API phục vụ tại `127.0.0.1:3000`;
worker là process duy nhất trong Compose có Docker socket để thực thi sandbox. API không được mount
socket này.

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

Các run có thể xem theo `platform_runs`, `platform_run_events`, `platform_run_steps` và
`platform_usage_records`. Không đọc prompt hoặc row data từ logs/metrics để điều tra; dùng artifact
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
