# Tạo MCP tool và cấp quyền

## 1. Cách pool hoạt động

Tool server-side là `McpPoolTool` trong `src/tool-pool.ts`. Module được nạp lúc API khởi động,
đăng ký vào một `McpToolPool`; mọi lần gọi đều qua pool để kiểm tra tên, agent allowlist, hàm
`authorize`, schema, timeout, hủy tác vụ và giới hạn JSON output 1 MB.

Một agent chỉ nhận tool từ giao của hai danh sách:

1. `descriptor.tools` của agent (Pi/runtime được plugin cho phép yêu cầu tool đó).
2. `tool.agents` trong tool pool (agent có quyền gọi tool).

`alwaysAvailable: true` chỉ thêm tool vào danh sách Pi ngay cả khi plugin không liệt kê tên đó;
pool vẫn enforce `agents`, `authorize` và schema. Không bật cờ này cho tiện lợi, ngoại trừ primitive
nền tảng có lý do rõ ràng như memory hoặc sandbox.

## 2. Contract của tool

| Thuộc tính | Ý nghĩa |
| --- | --- |
| `name` | Tên MCP duy nhất, tối đa 128 ký tự; dùng dạng namespace như `billing.lookup_invoice`. |
| `description` | Mô tả ngắn, chính xác để model hiểu khi nào dùng tool. |
| `schema` | JSON Schema TypeBox cho input; pool từ chối input không hợp lệ trước execute. |
| `mutates` | `true` nếu thay đổi dữ liệu/trạng thái; Pi tuần tự hóa tool này và MCP đặt `readOnlyHint` ngược lại. |
| `timeoutMs` | Tùy chọn 1-300000 ms; mặc định 30000 ms. |
| `agents` | ID agent được phép, hoặc `"*"` khi thực sự dùng chung. Không được để rỗng. |
| `alwaysAvailable` | Tùy chọn, mặc định false; luôn đưa vào tool manifest Pi, nhưng không cấp quyền. |
| `authorize(scope)` | Policy server-side, chạy mỗi lần gọi. Trả false nếu không được phép. |
| `execute(input, scope)` | Thực thi nghiệp vụ; phải tôn trọng `scope.signal`, trả JSON tối đa 1 MB. |

`ToolScope` có `userId`, `spaceId`, `agentId?`, `sessionId?`, `runId?`, `taskId?`, `depth?`,
`toolCallId?`, `publish?`, `signal`. Không lấy identity từ input của model nếu identity đã có trong
scope.

## 3. Viết tool module

Tool đơn giản dùng `defineTool` trong `src/tools/factory.ts`; pool vẫn kiểm tra schema, agent,
authorization, timeout, cancellation và output size:

```ts
import { Type } from "typebox";
import { defineTool } from "./factory.js";

export const tools = [
  defineTool({
    name: "inventory.lookup_item",
    description: "Read one item by SKU.",
    schema: Type.Object({ sku: Type.String({ minLength: 1, maxLength: 64 }) }),
    agents: ["summary"],
    authorize: (scope) => Boolean(scope.userId && scope.spaceId),
    async execute(input, scope) {
      scope.signal.throwIfAborted();
      return lookupItem((input as { sku: string }).sku, scope.spaceId);
    },
  }),
];

async function lookupItem(sku: string, spaceId: string) {
  return { sku, spaceId };
}
```

Ví dụ trên chỉ minh họa shape; repository thật phải đọc qua repository/provider có kiểm soát scope.
Đăng ký đường dẫn file vào `AGENT_TOOL_MODULES`, restart API, rồi thêm đúng tên tool vào
`descriptor.tools` hoặc `defineAgent({ tools })` của agent. Một tool được register vào pool một
lần và có thể cấp cho nhiều agent bằng `agents: ["agent-a", "agent-b"]` hoặc `"*"` khi thật sự
dùng chung.

Ví dụ tool chỉ đọc, cấp cho agent `data`:

```ts
import { Type } from "typebox";
import type { McpPoolTool } from "../tool-pool.js";

export const tools: McpPoolTool[] = [
  {
    name: "inventory.lookup_item",
    description: "Đọc một mặt hàng trong kho theo mã mặt hàng.",
    schema: Type.Object({ sku: Type.String({ minLength: 1, maxLength: 64 }) }),
    mutates: false,
    timeoutMs: 10_000,
    agents: ["data"],
    authorize(scope) {
      return scope.userId.length > 0 && scope.spaceId.length > 0;
    },
    async execute(input, scope) {
      scope.signal.throwIfAborted();
      const { sku } = input as { sku: string };
      const item = await lookupItemForSpace(sku, scope.spaceId, scope.signal);
      if (!item) return { found: false };
      return { found: true, item };
    },
  },
];

async function lookupItemForSpace(sku: string, spaceId: string, signal: AbortSignal) {
  signal.throwIfAborted();
  return { sku, spaceId };
}
```

Hàm `lookupItemForSpace` ở đây chỉ minh họa. Thay bằng service/repository thật và thêm kiểm soát
quyền ở cấp dữ liệu; không trả `spaceId` nội bộ như ví dụ minh họa trong sản phẩm.

Module có thể export `tools: McpPoolTool[]`, hoặc `createTools({ database })` trả danh sách tool
để nhận service dùng chung. Loader ở `src/tool-pool.ts` đăng ký từng tool; tên trùng làm API
khởi động thất bại. Đăng ký đường dẫn:

```dotenv
AGENT_TOOL_MODULES=src/tools/warehouse.ts,src/tools/inventory.ts
```

Nếu cấu hình biến này, liệt kê module warehouse hiện tại nếu vẫn cần chúng. Startup cũng tự gắn các
tool nền tảng `memory.*`, `sandbox.execute` (trừ khi `SANDBOX_PROVIDER=none`) và
`agents.delegate`; không đăng ký lại tên đó trong module riêng.

## 4. Cho agent nhận tool

Thêm tên tool vào `descriptor.tools` của plugin agent. Ví dụ:

```ts
descriptor: {
  id: "data",
  version: "1.0.0",
  name: "Data",
  description: "Truy xuất dữ liệu đã được cấp quyền.",
  input: Type.Object({ prompt: Type.String({ minLength: 1, maxLength: 4000 }) }),
  tools: ["inventory.lookup_item"],
}
```

Đồng thời đặt `agents: ["data"]` trong tool. Nếu thiếu một trong hai phía, agent không thể sử
dụng tool qua Pi; `GET /v1/tools` chỉ phản ánh pool allowlist theo `X-Agent-Id`, không phản ánh
manifest cụ thể của plugin. Sau khi đổi code/config phải restart API. Xác minh:

```sh
curl -sS http://localhost:3000/v1/tools \
  -H 'Authorization: Bearer <API_TOKEN>' \
  -H 'X-Agent-Id: data'
```

## 5. MCP endpoint cho client bên ngoài

`POST /mcp` dùng MCP Streamable HTTP. Caller gửi `X-Agent-Id` và token tương ứng
`AGENT_TOKEN_<AGENT_ID>` (ID được đổi thành chữ hoa, dấu khác chữ/số thành `_`). Server từ chối
agent chưa đăng ký hoặc token sai. Ví dụ `.env.example` có token placeholder cho cả sáu agent; hãy
thay bằng token local riêng nếu cần gọi MCP trực tiếp. UI và `/v1` không dùng các agent token này.
Ví dụ:

```sh
curl -sS http://localhost:3000/mcp \
  -H 'Authorization: Bearer <AGENT_TOKEN_DATA>' \
  -H 'X-Agent-Id: data' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Sau `tools/list`, client gọi `tools/call` với `params.name` và `params.arguments`. MCP lỗi tool
được trả dưới dạng nội dung có `isError: true`. Client bên ngoài chỉ có quyền của agent token đó;
không nhúng token trong frontend/browser.

## 6. Kết nối remote MCP

`defineRemoteMcpTool` trong `src/mcp-client-tool.ts` bọc remote tool thành một tool trong pool.
Module wrapper vẫn phải khai báo schema, `agents`, authorization và `remoteName`. Endpoint và
credential phải lấy từ trusted connection settings phía server. Helper bắt buộc HTTPS trừ
localhost; không cho model cung cấp endpoint, header hoặc token. Xử lý lỗi, timeout và giới hạn
kết quả remote như với mọi integration khác.

## 7. Memory dùng chung qua pool

API đăng ký `memory.remember`, `memory.search` và `memory.forget` cho mọi agent. Dữ liệu vẫn lưu
trong PostgreSQL, tách theo `(space_id, user_id, agent_id)`; mỗi agent chỉ thấy ghi nhớ của chính
nó trong đúng user/space. `memory.remember` nhận `key` tùy chọn để cập nhật ghi nhớ đã có; nếu bỏ
key, nội dung giống hệt được gộp theo hash. `memory.search` xếp hạng full-text trong PostgreSQL,
trả tối đa 8 mục. Pi tự gọi tìm kiếm liên quan trước mỗi lượt model và chỉ đưa tối đa 12 KB vào
context. `memory.forget` xóa một mục theo ID nhưng luôn ràng buộc cùng scope.

Ghi ngắn gọn những sở thích, quy tắc công việc hoặc sự kiện sẽ còn hữu ích về sau; không ghi token,
credential hay dữ liệu nhạy cảm không cần thiết. Dùng khóa ổn định cho mục cần cập nhật, ví dụ
`user.reporting-preference`, và xóa khi thông tin lỗi thời. Memory được đưa vào prompt như dữ liệu,
không có quyền ghi đè system prompt hay guardrail.

## 8. Guardrail và kiểm tra

- Ưu tiên read-only; với tool ghi, đặt `mutates: true`, xác minh đối tượng theo tenant/scope và
  thiết kế thao tác idempotent khi có thể.
- Schema phải giới hạn string, array, số dòng, trường tùy chọn và loại enum. Không nhận SQL/URL
  tự do trừ khi sản phẩm thật sự cần và có policy riêng.
- Không dùng `agents: ["*"]` để né thiết kế quyền. Chỉ dùng cho primitive có thể áp dụng an toàn
  cho mọi agent; vẫn kiểm tra user/space trong `authorize` và `execute`.
- Truyền `signal` xuống network/database; không nuốt cancellation. Đặt timeout hợp lý.
- Không trả secrets, stack trace, raw rows lớn hoặc dữ liệu ngoài scope. Pool giới hạn output JSON
  ở 1 MB.
- Test schema hợp lệ/sai, agent bị từ chối, authorize=false, timeout/cancel và output không JSON
  hoặc quá lớn bằng test offline deterministic.

Kiểm tra `corepack pnpm check`, `corepack pnpm test`, `corepack pnpm lint`, sau đó khởi động API,
xem `GET /v1/tools` và gọi `tools/list`/`tools/call` qua MCP bằng token local.
