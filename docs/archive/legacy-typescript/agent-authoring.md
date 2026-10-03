# Agent authoring guide

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

Agent mặc định của Team_6_cAi viết bằng Python (`agent-runner.v2`) trong thư mục `agents/`. Host
TypeScript chỉ chạy process, cấp tool, gọi model và ghi evidence. Team khác copy một agent trong
`agents/` làm mẫu, không cần sửa code TypeScript.

| Agent | File | Việc |
| --- | --- | --- |
| `orchestrator` | `agents/orchestrator.py` | Lập kế hoạch theo capability, delegate, trả lời từ evidence |
| `data` | `agents/data.py` | Tìm bảng, chạy query, tạo dataset `ds_…` |
| `compare` | `agents/compare.py` | So sánh số liệu (stats tính bằng code) |
| `insight` | `agents/insight.py` | Giải thích xu hướng có evidence |
| `visualize` | `agents/visualize.py` | Chọn trường, tạo chart `ch_…` |
| `report` | `agents/report.py` | Viết và lưu report `rp_…` |

Helper dùng chung ở `agents/_common.py` (prompt, model call, load dataset, stats).

## 1. Cài đặt (uv)

```sh
uv sync --project agents            # tạo agents/.venv, cài SDK (editable) theo uv.lock
uv sync --project agents --group langchain   # thêm ví dụ LangChain
```

Thêm thư viện: `uv add --project agents <pkg>==<version>` (luôn pin version), commit `uv.lock`.

## 2. Viết agent

```python
from _common import GUARDRAILS, PROMPT_INPUT, TEXT_OUTPUT, ask, prompt_of
from agent_platform import AgentContext, AgentManifest, serve

class SummaryAgent:
    manifest = AgentManifest(
        id="team.summary", version="1.0.0", name="Summary",
        description="Summarizes a dataset.",
        tools=("warehouse.describe_dataset", "warehouse.get_dataset_rows"),
        capabilities=("dataset.summary",),
        input_schema=PROMPT_INPUT, output_schema=TEXT_OUTPUT,
        model_profile="default",   # bật context.model; bỏ đi nếu agent không cần model
        guardrails=GUARDRAILS,
    )

    def run(self, value, context: AgentContext) -> str:
        rows = context.warehouse.get_dataset_rows("ds_...")
        return ask(context, "You summarize data.", prompt_of(value), rows)

if __name__ == "__main__":
    serve(SummaryAgent())
```

Quy tắc:

- Mọi truy cập dữ liệu đi qua `context.tools` / `context.warehouse`; chỉ tool có trong `tools` mới gọi được.
- Model chỉ gọi qua `context.model.text(prompt)` hoặc `context.model.json(prompt, schema)`. Host
  giữ key, áp budget, ghi usage và validate JSON theo schema. Runner xoá secret khỏi env của process
  con, nên agent không tự gọi provider.
- Port call lỗi thì SDK raise `RuntimeError`. Hãy bắt lỗi và fallback bằng dữ liệu đã tính, không đoán.
- Chỉ cite artifact id mà tool thật sự trả về.

## 3. Manifest và đăng ký

Manifest JSON sinh từ class Python, không sửa tay:

```sh
uv run --project agents python agents/gen_manifests.py          # ghi agents/manifests/*.json
uv run --project agents python agents/gen_manifests.py --check  # CI: báo lỗi nếu lệch
```

Agent mới ngoài roster: tự viết manifest với `"command": "uv"` và `"args": ["run", "--no-sync",
"--project", "agents", "python", "agents/<file>.py"]`, rồi đăng ký:

```sh
AGENT_EXTERNAL_MANIFESTS=agents/manifests/orchestrator.json,...,path/to/team.json
```

Để trống thì host nạp 6 agent mặc định. Đường dẫn tính từ thư mục chạy host (repo root, hoặc `/app`
trong Docker).

## 4. Test

```sh
corepack pnpm exec vitest run test/agent-plugins.test.ts   # roster Python, runtime giả
corepack pnpm exec tsx scripts/live-python-roster.mts      # model thật từ .env, trần $0.30
```

`test/support/python-roster.ts` dựng warehouse mock, artifact in-memory và delegate in-process, nên
chạy được mà không cần Postgres. Test có DB: `TEST_DATABASE_URL=... pnpm exec vitest run test/analytics-e2e.test.ts`.

## 5. Giới hạn

- Không có vòng lặp tool do model tự điều khiển; agent Python quyết định gọi tool nào bằng code.
- Input/output chỉ validate theo schema lúc chạy.
- Canary per-request chưa hỗ trợ cho external agent.

Module TypeScript `agent.v1` (`src/contracts`, `src/testkit`) vẫn được host hỗ trợ qua
`AGENT_PLUGIN_MODULES`, nhưng repo không còn agent TS mẫu. Ví dụ LangChain và A2A:
`sdk/python/examples/`. So sánh với vde-agent-demo: [comparison](comparison-vde-agent-demo.md).
