# Tạo và đăng ký agent

## 1. Agent gồm những gì?

Một agent trong runtime hiện tại là một `AgentPlugin` tin cậy được viết bằng TypeScript. Contract
được định nghĩa ở `src/agent-contract.ts`:

| Trường | Bắt buộc | Ý nghĩa |
| --- | --- | --- |
| `descriptor.id` | Có | ID ổn định, dùng trong URL, session, scope tool và token agent. Chỉ dùng chữ thường, số, `.`, `_`, `-`; ký tự đầu là chữ/số; tối đa 128 ký tự. |
| `descriptor.apiVersion` | Nên có | TypeScript mặc định dùng `agent-plugin.v1`; external manifest/Python dùng `agent-plugin.v2`. |
| `descriptor.version` | Có | Phiên bản module, hiện chỉ kiểm tra không rỗng. Nên theo SemVer. |
| `descriptor.name` | Có | Tên hiển thị của agent. |
| `descriptor.description` | Có | Mô tả vai trò để developer/UI nhận biết. |
| `descriptor.capabilities` | Nên có | Các capability được agent sử dụng, ví dụ `pi`, `durable-memory`, `docker-sandbox`. Đây là metadata; policy thật vẫn nằm ở host. |
| `descriptor.input` | Có | JSON Schema TypeBox cho input. Runtime kiểm tra schema trước khi gọi `run`. |
| `descriptor.output` | Nên có | JSON Schema TypeBox cho output. `/v1/agents/{id}/run` kiểm tra schema sau khi plugin hoàn tất. |
| `descriptor.guardrails` | Nên có | Các nguyên tắc ngắn để audit/hiển thị; không thay thế authorization/schema server-side. |
| `descriptor.tools` | Có | Tên các tool mà agent được phép yêu cầu. Pool vẫn kiểm tra allowlist và `authorize` trên mỗi lần gọi. |
| `run(input, context)` | Có | Hàm thực thi nghiệp vụ, trả `Promise<unknown>`. |

System prompt chưa phải trường riêng trong descriptor. Prompt là cấu hình triển khai do plugin sở
hữu và truyền vào Pi qua `context.runtime.prompt({ system, prompt, ... })`. Hãy viết prompt có vai
trò, phạm vi dữ liệu, quy trình khi thiếu bằng chứng, điều agent không được làm, định dạng kết quả
và giới hạn độ dài. Prompt không thay thế validation hay authorization trong code.

`AgentContext` gồm `runId`, `sessionId`, `userId`, `spaceId`, `signal`, danh sách `tools` đã chọn,
`runtime` Pi, `pool`, và các trường tùy chọn `taskId`, `depth`, `publish`. Tool runtime được gọi
qua `context.pool.call(...)`; chỉ dùng `context.tools` để thể hiện danh sách đã khai báo cho plugin.

## 2. Tạo plugin

Cách ngắn nhất là dùng `defineAgent` trong `src/agents/factory.ts`. Factory tự nối agent với
PiRuntime và truyền đúng scope/session/pool; developer chỉ khai báo manifest, prompt và input:

```ts
import { Type } from "typebox";
import { defineAgent } from "../factory.js";

export const agentPlugin = defineAgent({
  id: "summary",
  version: "1.0.0",
  name: "Summary",
  description: "Summarizes supplied text.",
  inputSchema: Type.Object({ text: Type.String({ minLength: 1, maxLength: 4000 }) }),
  tools: [],
  systemPrompt: "Summarize accurately. Say when the input is insufficient; do not invent facts.",
  prompt: (input) => (input as { text: string }).text,
});
```

Đặt file trên vào `src/agents/summary/index.ts`, rồi thêm module vào `AGENT_PLUGIN_MODULES`.
Nếu cần workflow đặc biệt, thêm `run(input, context)` vào definition; trong đó vẫn gọi
`context.runtime.prompt` hoặc logic TypeScript có kiểm soát. Không cần tạo route riêng cho agent.

Nếu không dùng factory, contract đầy đủ vẫn là `AgentPlugin` như ví dụ dưới đây:

```ts
import { Type } from "typebox";
import type { AgentPlugin } from "../../agent-contract.js";

export const agentPlugin: AgentPlugin = {
  descriptor: {
    id: "example.summary",
    version: "1.0.0",
    name: "Example summary",
    description: "Tóm tắt nội dung đầu vào dựa trên dữ liệu được cung cấp.",
    input: Type.Object({
      prompt: Type.String({ minLength: 1, maxLength: 4000 }),
    }),
    tools: [],
  },
  run(value, context) {
    const input = value as { prompt: string };
    return context.runtime.prompt({
      agentId: "example.summary",
      system:
        "Bạn là agent tóm tắt. Chỉ tóm tắt thông tin trong input; nêu rõ khi dữ liệu không đủ.",
      prompt: input.prompt,
      tools: context.tools.map((tool) => tool.name),
      scope: {
        userId: context.userId,
        spaceId: context.spaceId,
        sessionId: context.sessionId,
        runId: context.runId,
        taskId: context.taskId,
        depth: context.depth,
        signal: context.signal,
        publish: context.publish,
      },
      pool: context.pool,
    });
  },
};
```

Đây là ví dụ tối thiểu. Nếu agent không cần LLM, `run` có thể trả kết quả từ logic TypeScript mà
không gọi Pi. Nếu dùng Pi, runtime dùng chung provider/model cấu hình qua `PI_DEFAULT_PROVIDER`,
`PI_DEFAULT_MODEL`, `MODEL_API_KEY`; agent không tự tạo SDK/provider riêng.

## 2.1. Agent Python qua AgentRunner

Team chỉ viết Python dùng `sdk/python`, không cần import TypeScript, PostgreSQL, PiRuntime hoặc
private backend module. Host chạy một process Python riêng cho mỗi invocation và giao tiếp bằng
protocol `agent-runner.v1` JSONL. Python agent chỉ nhận input/scope và gọi tool qua host bridge;
ToolPool vẫn kiểm tra manifest, authorization, quota, timeout và trace ở mỗi call.

```python
from agent_platform import AgentContext, AgentManifest, serve


class RevenueAgent:
    manifest = AgentManifest(
        id="team.python.revenue",
        version="1.0.0",
        name="Python Revenue",
        description="Answers questions from verified warehouse data.",
        capabilities=("warehouse.query",),
        tools=("warehouse.list_sources", "warehouse.run_query"),
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string", "minLength": 1}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
    )

    def run(self, value: dict, context: AgentContext) -> dict:
        return {"prompt": value["prompt"], "sources": context.warehouse.list_sources()}


if __name__ == "__main__":
    serve(RevenueAgent())
```

Bridge messages `run`, `tool_call`, `tool_result`, `event`, `result` và `cancel` luôn có
`protocol`, `request_id` và `call_id` khi cần. Process Python không nhận PostgreSQL/Docker
credential; worker xử lý crash/retry/failure mà không làm API core chết.

## 3. Đưa agent vào AgentPool

Thêm module vào `AGENT_PLUGIN_MODULES`, phân tách nhiều đường dẫn bằng dấu phẩy:

```dotenv
AGENT_PLUGIN_MODULES=src/agents/index.ts,src/agents/summary/index.ts
```

Module TypeScript phải export `agentPlugin` đơn hoặc `plugins: AgentPlugin[]`. Python dùng manifest
JSON ngoài code và khai báo bằng `AGENT_EXTERNAL_MANIFESTS`:

```dotenv
AGENT_EXTERNAL_MANIFESTS=agents/python-revenue.json
```

Loader ở `src/registry.ts` validate cả hai loại manifest rồi gọi `AgentPool.register`. ID trùng,
ID sai định dạng hoặc protocol command thiếu làm agent bị từ chối trước khi nhận traffic.
Compose mặc định dùng `src/agents/index.ts`, nơi hiện đăng ký `orchestrator`, `data`, `compare`,
`insight`, `visualize`, `report`. Mỗi agent có thư mục riêng dưới `src/agents/`; logic workflow dùng chung nằm
ở `src/agents/analytics.ts`. Chỉ thay `AGENT_PLUGIN_MODULES` có thể vô tình bỏ roster mặc định,
do đó liệt kê cả module cũ lẫn module mới nếu muốn giữ các agent hiện hành.

Sau khi sửa module hoặc `.env`, khởi động lại API. Kiểm tra roster bằng:

```sh
curl -sS http://localhost:3000/v1/agents \
  -H 'Authorization: Bearer <API_TOKEN>'
```

`GET /v1/agents` trả metadata `{ apiVersion, id, version, name, description, capabilities,
inputSchema, outputSchema, guardrails, tools }`, không trả system prompt
hoặc API key.

## 4. Input/output và gọi thử

API operator chạy đúng schema đã khai báo:

```http
POST /v1/agents/example.summary/run
Authorization: Bearer <API_TOKEN>
Content-Type: application/json
```

```json
{
  "input": { "prompt": "Tóm tắt các kết quả đã xác minh." },
  "sessionId": "team-demo-01"
}
```

`sessionId` là tùy chọn; nếu bỏ qua server tạo ID mới. Kết quả `run` được serialize trực tiếp
thành JSON response. Vì vậy plugin nên trả string hoặc object JSON tương thích. Request sai schema
nhận `422`; agent không tồn tại nhận `404`; session Pi đang bận nhận `409`; lỗi thực thi nhận
`500`. Xem [API reference](api.md) để biết auth, ví dụ đầy đủ và UI API.

## 5. Đưa agent vào workflow team

Trong workflow chat, người dùng gửi nội dung qua `POST /api/agents/{agent}/messages`; nội dung
được đưa vào plugin dưới dạng input `{ prompt: content }`. Agent xuất hiện trong roster UI khi đã
được đăng ký lúc startup. `agents.delegate` vẫn là đường sync tương thích cho workflow hiện tại;
`agents.send` tạo child run durable để worker khác có thể tiếp tục, còn `agents.wait/result` đọc
trạng thái và output đã persist.

Agent team viết Python dùng các tool `agents.catalog`, `agents.send`, `agents.wait` và
`agents.result` trong manifest. `send` tạo child run durable và trả `runId`; `wait/result` chỉ đọc
run cùng `userId`, `spaceId` và task, nên agent không thể dò hoặc gọi agent ngoài tenant. Policy host
kiểm tra allowed edge, capability, depth, fan-out, kích thước message và quota trước khi enqueue.
Không gọi module TypeScript hoặc database trực tiếp để trao đổi giữa agent.

Agent thử nghiệm phải dùng fixture test riêng, không được đưa vào roster production; workflow tổng
hợp thuộc logic điều phối của `orchestrator`.

## 6. Guardrail bắt buộc

- Khai báo input schema có giới hạn độ dài, số lượng phần tử và enum hợp lệ; không nhận object tùy
  ý nếu không cần.
- Không tin system prompt là ranh giới bảo mật. Thực thi policy trong plugin/tool server-side,
  xác thực schema, kiểm tra scope và lọc kết quả theo user/space/agent.
- Chỉ khai báo tool cần thiết. Pool còn kiểm tra quyền theo `agents` và `authorize` khi tool được
  gọi. `alwaysAvailable` chỉ làm tool được Pi đưa vào danh sách chọn; không bỏ qua pool auth.
- Truyền `signal` để hủy tác vụ, không log token/credential, không nhận endpoint hay secret từ
  model input.
- Gắn mọi truy vấn memory/artifact vào scope của context. Memory và Pi session hiện được lưu trong
  PostgreSQL; identity riêng gồm `spaceId`, `userId`, `agentId` và, với Pi session, `sessionId`.
- Kết quả không được chứa dữ liệu không thuộc user/scope. Nêu rõ bằng chứng thiếu; không bịa ID
  artifact, số liệu hoặc việc specialist đã chạy.

## 7. Test và checklist đăng ký

Thêm test offline cho schema, output và nhánh lỗi của agent. Khi đổi contract chung hoặc orchestration,
thêm test tương ứng cho `AgentPool`, route hoặc workflow. Trước khi hoàn tất:

1. `corepack pnpm check`
2. `corepack pnpm test`
3. `corepack pnpm lint`
4. Khởi động API và gọi `GET /v1/agents`, sau đó chạy thử `/v1/agents/{id}/run` với input hợp lệ
   và input không hợp lệ.
