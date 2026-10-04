# HTTP và MCP API

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

Base URL local mặc định: `http://localhost:3000`. Backend phục vụ API và bản build frontend trên
cùng cổng. Endpoint `/v1/*` yêu cầu operator token; `/mcp` yêu cầu token riêng cho agent. UI API
dùng bearer web session khi `WEB_AUTH_MODE=session`; `X-User-Id` chỉ còn compatibility trong demo mode.

## Operator API (`/v1`)

Mọi request phải gửi `Authorization: Bearer <API_TOKEN>`.

### `GET /v1/agents`

Liệt kê manifest đã nạp:

```json
[
  {
    "id": "orchestrator",
    "apiVersion": "agent-plugin.v1",
    "version": "1.0.0",
    "name": "Orchestrator",
    "description": "Coordinates specialist agents.",
    "capabilities": ["pi", "durable-memory", "docker-sandbox"],
    "inputSchema": { "type": "object" },
    "outputSchema": { "type": "string" },
    "guardrails": ["Use only scoped evidence."],
    "tools": ["agents.delegate", "warehouse.describe_dataset"]
  }
]
```

Prompt hệ thống, schema đầy đủ và secrets không được trả ở endpoint này. Hiện agent đăng ký bằng
module TypeScript lúc startup, không qua HTTP create endpoint.

### `POST /v1/agents/{agentId}/run`

Chạy plugin trực tiếp, validate `input` bằng TypeBox schema của plugin. Request:

```json
{
  "input": { "prompt": "Liệt kê bảng bán hàng." },
  "sessionId": "analyst-session-01"
}
```

`input` bắt buộc. `sessionId` tùy chọn, dài 1-128 ký tự thuộc `[a-zA-Z0-9._:-]`; bỏ qua thì server
tạo ID. Response là giá trị JSON do `plugin.run` trả về. Ví dụ kết quả chuỗi:

```json
"Đã tìm thấy dataset ds_0123456789ab với 120 dòng."
```

Status lỗi: `401` token thiếu/sai; `404` không có agent; `422` thiếu `input`, session ID sai hoặc
input không khớp schema; `409` Pi session đang có run; `500` lỗi thực thi. Run có giới hạn thời
gian 180 giây và bị hủy khi client ngắt kết nối.

```sh
curl -sS http://localhost:3000/v1/agents/data/run \
  -H 'Authorization: Bearer <API_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"input":{"prompt":"Tìm bảng orders và mô tả các cột."}}'
```

### `GET /v1/tools`

Liệt kê tool trong pool theo header `X-Agent-Id`:

```sh
curl -sS http://localhost:3000/v1/tools \
  -H 'Authorization: Bearer <API_TOKEN>' \
  -H 'X-Agent-Id: data'
```

Response là mảng `{ name, description, inputSchema }`. Endpoint lọc theo `tool.agents`, không lọc
theo manifest `descriptor.tools`; xem [cách cấp tool](tools.md) để biết cần cấu hình cả hai phía.

## MCP API

### `POST /mcp`

MCP Streamable HTTP dùng token riêng của agent:

- `Authorization: Bearer <AGENT_TOKEN_<ID>>`
- `X-Agent-Id: <agent-id>`
- `Content-Type: application/json`
- `Accept: application/json, text/event-stream`

Hỗ trợ `tools/list` và `tools/call`. `tools/list` chỉ trả tool pool cấp cho agent. Với
`tools/call`, server chạy lại allowlist, authorization và input schema. Xem [hướng dẫn MCP](tools.md).

## Health check

`GET /live` (alias `GET /health`) trả `{ "status": "ok" }` khi process còn sống; không kiểm
dependency. Dùng cho liveness probe.

`GET /ready` trả `503` khi process đang start hoặc drain, khi PostgreSQL không trả lời, hoặc khi
schema database chưa khớp image. Dùng cho readiness probe; chi tiết drain ở
[operations](operations.md). `GET /metrics` trả text Prometheus; metric labels không chứa
identity, prompt, query result hoặc secret.

## Versioned API, MCP và A2A

- `/api/v1/*`: registry/activation/plan/run/step/checkpoint/memory/evidence, cursor replay,
  idempotency và legacy adapter. Contract: [web-api-v1](contracts/platform-api.md).
- `/mcp`: resources/tools với auth, audience và size limit. Contract: [mcp-server](contracts/mcp-server.md).
- `/.well-known/agent-card.json` và `/a2a`: gateway A2A tùy chọn với rate limit và tenant mapping.
  Contract: [a2a-gateway](contracts/a2a-gateway.md).
- Browser/API security negatives: [security-negatives](contracts/security-negatives.md).

## UI/workflow API (`/api`)

Ở demo mode, các endpoint này dùng header `X-User-Id` với ID đã tạo/chọn. Ở session mode, gửi
`Authorization: Bearer <web-session>`; server chỉ trả user thuộc session và không chấp nhận spoof
`X-User-Id`. Không dùng API token operator hoặc agent token trong frontend.

| Method | Path | Request/response chính |
| --- | --- | --- |
| `GET` | `/api/users` | Mảng `{ id, name }`, user tạo gần nhất đứng đầu. |
| `POST` | `/api/users` | Demo mode: body `{ "name": "Analyst" }`, trả user mới `201`; session mode khóa provisioning và trả `403`. |
| `GET` | `/api/agents` | Cần user header; mảng `{ name, description, healthy, busy, queue_len }` từ registry. |
| `GET` | `/api/agents/{agent}/messages?before_seq=&limit=` | Lịch sử `{ summary, messages, pending }`; mặc định 50, tối đa 200. |
| `POST` | `/api/agents/{agent}/messages` | Body `{ "content": "..." }`; tạo task/run async, trả `{ task_id, invocation_id, run_id }`, status `202`. |
| `GET` | `/api/tasks?status=running` | Tối đa 50 task gần nhất; status có thể là `running`, `completed`, `failed`, `cancelled`. |
| `GET` | `/api/tasks/{taskId}` | `{ task, invocations }`, chỉ trong phạm vi user. |
| `POST` | `/api/tasks/{taskId}/cancel` | Hủy task đang chạy; trả `{ task }`. Nếu đã kết thúc, `409`. |
| `GET` | `/api/events?user_id={id}&after={cursor}` | SSE stream theo authenticated user; replay tối đa 1000 event từ cursor. |
| `GET` | `/api/reports` | Danh sách 100 report gần nhất `{ id, title, created_at }`. |
| `GET` | `/api/datasets/{id}?offset=&limit=` | Dataset và trang rows; mặc định 200, tối đa 1000. |
| `GET` | `/api/charts/{id}` | Chart `{ id, title, dataset_id, spec }`. |
| `GET` | `/api/reports/{id}` | Report `{ id, title, markdown, created_at }`. |

### SSE event contract

`GET /api/events?user_id={id}` phát ba event hiện được workflow API sử dụng. Mỗi SSE `data` là
JSON có các trường sau:

| Event | Payload |
| --- | --- |
| `message.appended` | `{ "agent": "data", "message": MessageDTO }` |
| `invocation.updated` | `{ "invocation": InvocationDTO }` |
| `task.updated` | `{ "task": TaskDTO }` |

Mỗi event có `id` tăng dần theo user và được lưu trong PostgreSQL. Client có thể gửi `after={id}`
hoặc header `Last-Event-ID` để replay tối đa 1000 event bị lỡ. Khi reconnect, frontend tiếp tục từ
cursor này; REST vẫn là nguồn đọc trạng thái cuối thay vì coi SSE là nguồn duy nhất.

Ví dụ tạo user và gửi yêu cầu:

```sh
curl -sS http://localhost:3000/api/users \
  -H 'Content-Type: application/json' \
  -d '{"name":"Analyst"}'

curl -sS http://localhost:3000/api/agents/orchestrator/messages \
  -H 'X-User-Id: <USER_ID>' \
  -H 'Content-Type: application/json' \
  -d '{"content":"So sánh doanh thu theo tháng và tạo báo cáo."}'
```

`X-User-Id` phải trỏ đến user tồn tại trong demo mode. Session mode yêu cầu token có subject đã
provision trong `web_users`; token hết hạn hoặc sai chữ ký nhận `401`. Lỗi UI API thường theo dạng
`{ "error": { "code": "...", "message": "..." } }`; các response thành công giữ snake_case theo
contract hiện tại.

Trong session mode, `/api/users` chỉ trả user hiện tại và `POST /api/users` bị khóa; user được
provision qua identity provider. `EventSource` dùng query `user_id` nhưng server vẫn yêu cầu bearer
session và kiểm tra query trùng subject, nên query không phải credential.

## Phân quyền và đăng ký

Không có API HTTP tạo agent, đăng ký tool, sửa pool hoặc cấp tool cho agent. Các thao tác đó là
thay đổi module/config phía backend, sau đó restart deployment. `GET` API trên chỉ đọc registry
hiện tại. Migrations PostgreSQL chạy lúc startup. Xem [agent guide](agents.md) và
[tool guide](tools.md) để triển khai thay đổi.
