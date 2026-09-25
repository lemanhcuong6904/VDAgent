# Team 6 cAi

VDaAgent là nền tảng agent phân tích dữ liệu theo hướng API-first. Repository này triển khai một
modular monolith bằng TypeScript: Hono API lắp ráp agent và MCP tool, Pi Agent Core chạy vòng
model/tool, PostgreSQL lưu trạng thái bền vững, Docker cung cấp sandbox, còn React cung cấp giao
diện local để gửi yêu cầu và xem task, dataset, chart, report.

## Chức năng hiện tại

Roster mặc định có sáu agent:

| Agent | Vai trò |
| --- | --- |
| `orchestrator` | Hiểu yêu cầu, điều phối specialist và tổng hợp câu trả lời. |
| `data` | Khám phá warehouse, truy vấn dữ liệu và lưu dataset. |
| `compare` | So sánh kỳ hoặc nhóm dữ liệu đã truy xuất. |
| `insight` | Phân tích xu hướng, nêu evidence và đánh dấu giả thuyết. |
| `visualize` | Chọn dữ liệu và tạo chart dựa trên kết quả Compare/Insight. |
| `report` | Viết report từ kết quả Compare, Insight và Visualize. |

Luồng report: `orchestrator → data → compare + insight → visualize → report`. Warehouse mặc định
là mock data để chạy local; provider warehouse có thể được thay bằng implementation khác. Agent
và tool là TypeScript plugin tin cậy được nạp lúc API khởi động, chưa có API HTTP để upload hoặc
tạo module động.

## Yêu cầu

- Node.js 22 trở lên và Corepack.
- Docker Engine/Desktop cùng Docker Compose; Docker daemon phải chạy để dùng sandbox.
- API key cho model đã cấu hình. Mặc định dùng provider/model trong `.env.example`.

## Chạy local bằng Docker

Tại thư mục gốc repository:

```sh
corepack pnpm install --frozen-lockfile
npm --prefix frontend ci
cp .env.example .env
```

Trong `.env`, thay `API_TOKEN` và `POSTGRES_PASSWORD` bằng giá trị local riêng; cập nhật cùng mật
khẩu trong `DATABASE_URL`. Điền `MODEL_API_KEY` cho provider/model đang dùng. Không commit `.env`
hoặc đưa secret thật vào issue, log hay tài liệu.

Khởi động PostgreSQL, API và frontend đã build:

```sh
docker compose up --build -d
```

Mở giao diện tại <http://localhost:3000>. Kiểm tra API bằng:

```sh
curl -fsS http://localhost:3000/health
docker compose ps
docker compose logs -f api
```

API container mount Docker socket của host để tạo sandbox container. Không tắt Docker khi chạy
workflow cần sandbox. PostgreSQL dùng named volume `postgres-data`; lệnh `docker compose down`
giữ dữ liệu. Chỉ dùng `docker compose down -v` khi chủ ý xóa toàn bộ database local.

### Frontend hot reload

Giữ API và database trong Docker, sau đó chạy Vite trên host:

```sh
docker compose up -d database api
npm --prefix frontend run dev -- --host 127.0.0.1
```

Mở <http://localhost:5173>. Vite proxy các request `/api` và SSE tới API ở cổng 3000.

## API và bảo mật

- `GET /health`: health check.
- `/api/*`: workflow UI gồm users, agents, messages, tasks, events (SSE), datasets, charts và reports.
- `/v1/*`: operator API; gửi `Authorization: Bearer <API_TOKEN>` để liệt kê agent/tool hoặc chạy agent.
- `POST /mcp`: MCP Streamable HTTP; gửi `X-Agent-Id` và token riêng của agent.

Frontend local hiện dùng `X-User-Id` làm user scope. Đây là cơ chế cho demo/local, chưa phải xác
thực người dùng để mở internet công khai. Trước khi deploy public, cần gắn identity đã xác thực
với user/space scope và cấu hình secret trong secret manager. Không đưa operator token, agent token
hay provider key vào browser.

Tham khảo contract, request/response, lỗi và ví dụ gọi tại [HTTP/MCP API](docs/api.md).

## Agent, tool, memory và sandbox

Agent đăng ký qua `AGENT_PLUGIN_MODULES`; MCP tool đăng ký qua `AGENT_TOOL_MODULES`. Mỗi agent
khai báo input/output schema, prompt, guardrail và tool được phép. Quyền tool cần khớp manifest
agent với allowlist/authorization của tool pool. Sau khi sửa module hoặc cấu hình, khởi động lại
API để nạp thay đổi.

Memory riêng của agent và Pi session được lưu bền vững trong PostgreSQL, có scope theo space, user
và agent; mỗi agent chỉ truy vấn được memory của chính nó trong scope đó. Dữ liệu không chỉ nằm
trong RAM. Sandbox dùng Docker container với workspace persistent tách theo `(space, user, agent)`.
Các sandbox dùng chung thư viện có sẵn trong image cấu hình `SANDBOX_IMAGE`; workspace và file làm
việc được cô lập riêng. Xem chi tiết tại [agent guide](docs/agents.md), [MCP tool guide](docs/tools.md)
và [architecture](docs/architecture.md).

## Kiểm tra và phát triển

```sh
corepack pnpm check
corepack pnpm lint
corepack pnpm test
corepack pnpm frontend:build
npm --prefix frontend test
```

Frontend và backend dùng cùng API contract. End-to-end workflow test nằm trong
`test/analytics-e2e.test.ts`; test mặc định deterministic/offline. Khi đổi schema PostgreSQL, thêm
migration mới dưới `db/migrations/`.

## Cấu trúc repository

```text
src/agents/       Agent plugin và roster mặc định
src/tools/        MCP tool và orchestration tool
src/              API, Pi runtime, registry, memory, sandbox, warehouse
frontend/         React + Vite client
db/migrations/    PostgreSQL migrations
test/             Backend, integration và E2E workflow tests
docs/             API, architecture, agent/tool guide và folder ownership
```

Đọc [docs index](docs/README.md) để tìm hướng dẫn theo công việc. [Folder ownership](docs/folder-ownership.md)
mô tả ranh giới giữa các nhóm để giảm xung đột khi phát triển song song.
