# Team 6 cAi

Multi-agent platform với evidence ledger, fail-closed tool grants và durable execution.

## Tổng quan

Host TypeScript (API, worker, PostgreSQL) chạy các agent Python qua protocol `agent-runner.v2`:

- **Fail-closed tool grants**: agent chỉ gọi được tool khai trong manifest và được tool pool cho phép.
- **Model qua host**: agent gọi `context.model`; key nằm ở server, usage ghi vào `platform_usage_records`.
- **Durable execution**: PostgreSQL lưu task, invocation, message và event; worker lease/retry.
- **Process isolation**: mỗi agent là process riêng, env đã xoá secret, giao tiếp JSONL stdin/stdout.
- **Framework tuỳ ý**: agent là Python thuần; có ví dụ LangChain và A2A trong `sdk/python/examples/`.

## Agents

Roster mặc định gồm sáu agent Python trong `agents/`, nạp từ `agents/manifests/*.json`:

| Agent | Vai trò |
| --- | --- |
| `orchestrator` | Hiểu yêu cầu, lập kế hoạch theo capability, delegate và tổng hợp câu trả lời |
| `data` | Khám phá warehouse, truy vấn dữ liệu và lưu dataset |
| `compare` | So sánh kỳ hoặc nhóm dữ liệu đã truy xuất |
| `insight` | Phân tích xu hướng, nêu evidence và đánh dấu giả thuyết |
| `visualize` | Chọn trường và tạo chart dựa trên kết quả Compare/Insight |
| `report` | Viết report từ kết quả Compare, Insight và Visualize |

Luồng report: `orchestrator → data → compare → insight → visualize → report`. Team khác copy một file
trong `agents/` làm mẫu; xem [agent authoring](docs/agent-authoring.md).

## Yêu cầu

- Node.js 22 trở lên và Corepack; [uv](https://docs.astral.sh/uv/) cho Python agent (`uv sync --project agents`).
- Docker Engine/Desktop cùng Docker Compose; Docker daemon chỉ bắt buộc khi bật sandbox Docker riêng.
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
hoặc đưa secret thật vào issue, log hay tài liệu. Nếu cần kết nối MCP trực tiếp, thay các
`AGENT_TOKEN_*` placeholder bằng token riêng tương ứng; các token này không dùng trong browser.

Có thể khai báo thêm model profile bằng `MODEL_PROFILES_JSON` (mảng JSON không chứa secret). Agent
chọn profile qua manifest; credential vẫn chỉ nằm ở server-side environment hoặc secret manager.

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

Bật stack quan sát tùy chọn bằng `docker compose --profile observability up -d`; xem
[operations guide](docs/operations.md) để biết readiness, outbox, backup và session auth.

Production Compose mặc định không mount Docker socket và đặt `SANDBOX_PROVIDER=none`, vì socket trao
quyền quản trị Docker trên host. Nếu deployment riêng cần sandbox Docker, hãy dùng supervisor tin cậy,
mount socket có chủ ý và đặt `DOCKER_GID`; API vẫn không được mount socket. PostgreSQL dùng named volume
`postgres-data`; lệnh `docker compose down` giữ dữ liệu. Chỉ dùng `docker compose down -v` khi chủ ý
xóa toàn bộ database local.

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

Frontend local dùng `X-User-Id` trong demo mode. Public deployment phải bật `WEB_AUTH_MODE=session`,
gắn identity provider/OIDC gateway với `web_users`, và cấu hình secret trong secret manager. Không
đưa operator token, agent token hay provider key vào browser.

Tham khảo contract, request/response, lỗi và ví dụ gọi tại [HTTP/MCP API](docs/api.md).

## Agent, tool, memory và sandbox

**Agent**: viết bằng Python với SDK `agent_platform` (`sdk/python/`), không cần biết TypeScript hay
PostgreSQL. Để trống `AGENT_EXTERNAL_MANIFESTS` thì host nạp roster mặc định; đặt danh sách manifest
(phân tách bằng dấu phẩy) để thay hoặc thêm agent. Module TypeScript `agent.v1` vẫn nạp được qua
`AGENT_PLUGIN_MODULES` (mặc định rỗng).

**Tool grants**: quyền tool phải khớp manifest agent với allowlist/authorization của tool pool. Fail-closed:
denied khi không grant. MCP tools đăng ký qua `AGENT_TOOL_MODULES`.

**Memory**: PostgreSQL-backed, scope theo `(space, user, agent)`. Mỗi agent chỉ truy vấn memory của chính nó.

**Sandbox**: Production Compose tắt Docker sandbox mặc định để không cấp quyền host qua Docker socket.
Deployment riêng có thể bật Docker containers với workspace persistent tách theo `(space, user, agent)`
qua `SANDBOX_PROVIDER=docker` và supervisor tin cậy. Image: `SANDBOX_IMAGE`.

Xem chi tiết: [agent authoring](docs/agent-authoring.md), [architecture](docs/architecture.md), [tools](docs/tools.md).

## Kiểm tra và phát triển

```sh
corepack pnpm check
corepack pnpm lint
corepack pnpm test
corepack pnpm exec tsx scripts/live-python-roster.mts   # model thật từ .env, trần $0.30
corepack pnpm frontend:build
npm --prefix frontend test
```

Frontend và backend dùng cùng API contract. Unit tests mặc định deterministic/offline. PostgreSQL
integration tests, gồm end-to-end workflow test trong `test/analytics-e2e.test.ts`, chỉ chạy khi đặt
`TEST_DATABASE_URL` trỏ tới database test riêng; nếu không, các suite đó được skip. Khi đổi schema
PostgreSQL, thêm migration mới dưới `db/migrations/`.

## Cấu trúc repository

```text
agents/           Python agents mặc định (uv project) và manifests
sdk/python/       Python SDK agent_platform và ví dụ
src/tools/        MCP tool và orchestration tool
src/              API, Pi runtime, registry, memory, sandbox, warehouse
frontend/         React + Vite client
db/migrations/    PostgreSQL migrations
test/             Backend, integration và E2E workflow tests
docs/             API, architecture, agent/tool guide và folder ownership
```

Đọc [docs index](docs/README.md) để tìm hướng dẫn theo công việc. [Folder ownership](docs/folder-ownership.md)
mô tả ranh giới giữa các nhóm để giảm xung đột khi phát triển song song.
