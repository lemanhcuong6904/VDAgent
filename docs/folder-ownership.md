# Cấu trúc thư mục và quyền sở hữu

Mục tiêu của phân vùng là để team biết nơi thêm code và contract họ được sửa. Cây bên dưới phản
ánh repository hiện tại. Bảng ownership mô tả domain kỹ thuật; tên nhánh, quyền push và luồng PR
được quy định tại [`GIT_RULE.md`](../GIT_RULE.md). Không tự ý đổi đường dẫn module trong `.env`,
Dockerfile hoặc Compose mà không cập nhật startup/test/deploy.

## Cây hiện tại

```text
.
├── src/
│   ├── agents/              # Sáu agent runtime và roster startup
│   │   ├── orchestrator/    # Điều phối workflow
│   │   ├── data/            # Truy xuất và persist dataset
│   │   ├── compare/         # So sánh dataset
│   │   ├── insight/         # Giải thích xu hướng
│   │   ├── visualize/       # Chọn và tạo chart
│   │   ├── report/          # Tổng hợp findings và lưu report
│   │   ├── analytics.ts     # Workflow analytics dùng chung
│   │   └── factory.ts       # defineAgent helper
│   ├── tools/               # MCP tools và tool pool modules
│   ├── providers/warehouse/ # Warehouse provider; hiện có mock adapter
│   ├── agent-contract.ts    # AgentPlugin và AgentContext
│   ├── registry.ts          # AgentPool và startup module loader
│   ├── tool-pool.ts         # MCP tool contract và authorization
│   ├── pi-runtime.ts        # Pi Agent Core adapter
│   ├── pi-session-store.ts  # Pi session persistence contract
│   ├── memory-store.ts      # Durable agent memory tools/provider contract
│   ├── sandbox.ts           # Sandbox contract và tool registration
│   ├── docker-sandbox.ts    # Docker execution adapter
│   ├── database.ts          # PostgreSQL migrations
│   ├── postgres-store.ts    # PostgreSQL memory/session stores
│   ├── warehouse.ts         # Warehouse contract, registry và tools
│   ├── warehouse-artifacts.ts # PostgreSQL artifact store
│   ├── web-api.ts           # UI/workflow API và SSE events
│   └── server.ts            # Composition root
├── frontend/
│   └── src/                # React UI: api, events, components, chat, inspector, ui
├── db/
│   └── migrations/         # Schema PostgreSQL phiên bản hóa
├── test/                   # Backend tests
├── docs/                   # Tài liệu developer/API/architecture/ownership
├── package.json            # Backend scripts/dependencies
├── frontend/package.json   # Frontend dependencies/scripts
├── Dockerfile              # Build frontend và đóng gói API runtime
└── docker-compose.yml      # API + PostgreSQL local và Docker socket cho sandbox
```

## Ownership theo thư mục đang có

| Vùng | Team chịu trách nhiệm | Có thể sửa | Cần phối hợp khi |
| --- | --- | --- | --- |
| `src/agent-contract.ts`, `src/registry.ts` | Platform/agent runtime | Contract và loader agent | Thêm field/thay đổi lifecycle ảnh hưởng mọi plugin hoặc API consumer. |
| `src/agents/<agent>/`, `src/agents/analytics.ts` | Agent workflow | Prompt, schema, manifest, logic của agent thuộc team | Đổi delegation, roster mặc định, input contract public hoặc output UI. |
| `src/tool-pool.ts`, `src/mcp-server.ts`, `src/mcp-client-tool.ts` | Platform/tools | Pool policy, MCP boundary, adapter | Đổi schema/policy/cấp quyền hoặc tương thích MCP. |
| `src/tools/` | Team domain/integration tương ứng | Tool schema, service adapter, test của integration | Tool dùng chung, thay permission/schema hoặc tạo migration. |
| `src/warehouse.ts`, `src/providers/warehouse/` | Data platform | Provider contract và warehouse adapter | Đổi semantics query/artifact hoặc cấp thêm warehouse credential. |
| `src/web-api.ts`, `src/agent-guardrails.ts` | Backend/API | Workflow REST, task lifecycle, API validation | Thay response/API contract, database writes hoặc auth. |
| `src/pi-runtime.ts`, `src/pi-session-store.ts` | Runtime team | Pi adapter và persistence boundary | Thay provider config, session semantics hoặc tool translation. |
| `src/sandbox.ts`, `src/docker-sandbox.ts` | Sandbox/platform security | Sandbox contract và Docker adapter | Mọi thay đổi Docker socket, isolation, image, command policy. |
| `src/database.ts`, `src/postgres-store.ts`, `src/memory-store.ts`, `src/pi-session-store.ts`, `src/warehouse-artifacts.ts`, `db/migrations/` | Data persistence | Schema, memory/session stores và PostgreSQL adapters | Thay data ownership, migrations, isolation hoặc retention. |
| `frontend/src/api/` | Frontend/API integration | API types, client, query hooks | Backend response/API thay đổi. |
| `frontend/src/components/`, `chat/`, `inspector/`, `events/`, `ui/` | Frontend | UI, state rendering, SSE handling | Cần endpoint/event mới hoặc thay payload backend. |
| `test/` và `frontend/src/**/*.test.*` | Từng team theo feature | Tests cho vùng team sở hữu | Contract chung cần test end-to-end/offline. |
| `docs/` | Mọi team, thay đổi theo ownership | Tài liệu vùng phụ trách | Thay API/contract cần cập nhật API, architecture và guide liên quan cùng PR. |
| `Dockerfile`, `docker-compose.yml`, `.env.example`, `package.json` | Build/release/platform | Build, local env, dependency | Đổi startup paths, migrations, secrets hoặc deployment. |

Các tên team trong bảng ownership là owner theo domain, không tự cấp quyền Git. Khi một thay đổi
chạm nhiều domain, tác giả cần phối hợp với các owner tương ứng; nhánh đích và reviewer vẫn theo
`GIT_RULE.md`.

## Ranh giới khi nhiều team cùng làm

- Agent team sở hữu plugin và system prompt của agent. Agent team không tự sửa authorization chung
  trong pool để khiến tool của mình được mở rộng quyền.
- Tool/integration team sở hữu tool module và adapter của dịch vụ. Họ không sửa roster agent để
  cấp chính mình cho agent khác; yêu cầu đó đi qua owner agent và review policy.
- Platform team sở hữu contract dùng chung (`AgentPlugin`, `McpPoolTool`, `WarehouseProvider`,
  `SandboxProvider`), loader, runtime và auth. Thay contract phải kèm migration plugin consumers,
  tests và tài liệu.
- Backend/API team sở hữu workflow/public endpoint và payload. Frontend tiêu thụ contract qua
  `frontend/src/api`; không tạo endpoint giả chỉ để UI hoạt động.
- Data/persistence team sở hữu migrations và quyền đọc/ghi dữ liệu. Mọi migration phải có phiên
  bản, idempotency phù hợp startup và test ở luồng dùng dữ liệu.
- Không sửa trực tiếp file agent/tool thuộc team khác. Tách module riêng, rồi yêu cầu owner thay
  manifest/roster hoặc review tích hợp.

## Quy ước thêm agent/tool ngay bây giờ

Để giảm va chạm trước khi có package workspace riêng:

```text
src/agents/<team>-<agent>/index.ts
src/tools/<team>-<domain>.ts
test/<team>-<domain>-agent.test.ts
test/<team>-<domain>-tools.test.ts
docs/<team>-<domain>.md              # Chỉ khi domain có quy trình riêng đáng tài liệu hóa
```

Ví dụ path module phải được thêm vào `AGENT_PLUGIN_MODULES` hoặc `AGENT_TOOL_MODULES`. Nhiều team
cùng chỉnh `.env.example`/Compose có thể conflict; platform owner tổng hợp cấu hình startup thay vì
để mỗi team đổi default roster riêng.

## Cây mục tiêu khi tách team/package

Đây là đích tổ chức đề xuất nếu số team tăng. Giữ contract trong package dùng chung và plugin trong
workspace riêng theo domain; không chuyển file sang cây này nếu chưa cập nhật import, build,
Dockerfile, tests và module paths:

```text
packages/
├── contracts/               # Agent/tool/warehouse/sandbox contracts và JSON schemas
├── agent-sdk/                # Helpers để tạo plugin theo contract; không sở hữu orchestration
├── tool-sdk/                 # Helpers/schema cho MCP tool authoring
└── testkit/                  # Fake Pi/database/warehouse và conformance fixtures offline
apps/
├── api/                      # Hono routes, auth, orchestration, composition root
└── web/                      # React frontend và API client
agents/
├── orchestrator/             # Plugin, prompt, workflow tests, README riêng
├── data/
├── compare/
├── insight/
├── visualize/
└── report/
integrations/
├── warehouse-mock/
├── warehouse-<provider>/     # Adapter riêng, credentials qua generic connection config
└── <domain>-mcp/             # Tools thuộc integration/domain
providers/
├── pi/                       # PiRuntime adapter
├── postgres/                 # Persistence providers/migrations
└── docker-sandbox/           # Docker-only execution adapter
docs/
└── ...                       # API, architecture, agent/tool guides, team ownership
```

Không tạo bản sao contract trong từng team. Mọi agent/tool cùng import `src/agent-contract.ts`
và `src/tool-pool.ts` cho đến khi migration workspace/package được thực hiện thành một thay đổi riêng.

## Quy tắc PR và kiểm tra

PR chỉ sửa một ownership domain nếu có thể. Khi thay shared contract, nêu rõ consumers được cập
nhật và thêm test offline. Không commit `.env`, token thật, data warehouse thật hoặc dữ liệu cá
nhân. Trước handoff chạy:

```sh
corepack pnpm format
corepack pnpm lint
corepack pnpm check
corepack pnpm test
corepack pnpm frontend:build
npm --prefix frontend test
git diff --check
```

`format` chỉ áp dụng formatter, không thay thế lint. Xem README để biết lệnh chạy stack local.
