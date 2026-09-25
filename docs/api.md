# HTTP và MCP API

Base URL local mặc định: `http://localhost:3000`. Backend phục vụ API và bản build frontend trên
cùng cổng. Endpoint `/v1/*` yêu cầu operator token; `/mcp` yêu cầu token riêng cho agent; UI API
hiện dùng `X-User-Id` làm nhận diện người dùng trong demo. Đây chưa phải cơ chế xác thực người dùng
cho môi trường public production.

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

## UI/workflow API (`/api`)

Các endpoint này dùng header `X-User-Id` với ID đã tạo/chọn. Không dùng API token operator hoặc
agent token trong frontend.

| Method | Path | Request/response chính |
| --- | --- | --- |
| `GET` | `/api/users` | Mảng `{ id, name }`. |
| `POST` | `/api/users` | Body `{ "name": "Analyst" }`; trả user mới, status `201`. |
| `GET` | `/api/agents` | Cần user header; mảng `{ name, description, healthy, busy, queue_len }` từ registry. |
| `GET` | `/api/agents/{agent}/messages?before_seq=&limit=` | Lịch sử `{ summary, messages, pending }`; mặc định 50, tối đa 200. |
| `POST` | `/api/agents/{agent}/messages` | Body `{ "content": "..." }`; tạo task async, trả `{ task_id, invocation_id }`, status `202`. |
| `GET` | `/api/tasks?status=running` | Tối đa 50 task gần nhất; status có thể là `running`, `completed`, `failed`, `cancelled`. |
| `GET` | `/api/tasks/{taskId}` | `{ task, invocations }`, chỉ trong phạm vi user. |
| `POST` | `/api/tasks/{taskId}/cancel` | Hủy task đang chạy; trả `{ task }`. Nếu đã kết thúc, `409`. |
| `GET` | `/api/events?user_id={id}` | SSE event stream của user, gồm cập nhật message/task/invocation. |
| `GET` | `/api/reports` | Danh sách 100 report gần nhất `{ id, title, created_at }`. |
| `GET` | `/api/datasets/{id}?offset=&limit=` | Dataset và trang rows; mặc định 200, tối đa 1000. |
| `GET` | `/api/charts/{id}` | Chart `{ id, title, dataset_id, spec }`. |
| `GET` | `/api/reports/{id}` | Report `{ id, title, markdown, created_at }`. |

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

`X-User-Id` phải trỏ đến user tồn tại. User API hiện là demo/local interface; cần lớp xác thực và
authorization phù hợp trước khi mở public. Lỗi UI API thường theo dạng
`{ "error": { "code": "...", "message": "..." } }`; các response thành công giữ snake_case theo
contract hiện tại.

## Phân quyền và đăng ký

Không có API HTTP tạo agent, đăng ký tool, sửa pool hoặc cấp tool cho agent. Các thao tác đó là
thay đổi module/config phía backend, sau đó restart deployment. `GET` API trên chỉ đọc registry
hiện tại. Migrations PostgreSQL chạy lúc startup. Xem [agent guide](agents.md) và
[tool guide](tools.md) để triển khai thay đổi.
