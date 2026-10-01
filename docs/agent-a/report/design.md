# Report Agent — thiết kế hiện tại (Python, LangGraph)

30/09/2026. Mô tả kiến trúc **thật sự đang chạy**, đọc trực tiếp từ code ở
`agents/report/vdagent_report/`. Không suy diễn từ `task-contract-v0.1.md` (draft cũ, xem cảnh
báo ở đầu file đó) hay từ tài liệu TypeScript trong `docs/agent-a/report/README.md` bản trước.

## 1. Code ở đâu

| File | Vai trò |
| --- | --- |
| `agent.py` | Entry point plugin: `build_agent`, `LangGraphAgent` (mở MCP session, chạy graph, `compact`) |
| `graph.py` | `ReportTurn` — một lượt turn là một `StateGraph` LangGraph hand-built |
| `judge.py` | `JevJudge` / `Judge` — quality gate gọi Jev qua OpenRouter decisions endpoint |
| `mcp_client.py` | Bọc MCP session: `list_tools`, `call_tool`, timeout, truncation |
| `settings.py` | Đọc `.env` của plugin (`OPENAI_API_KEY`, `LLM_MODEL`, `JUDGE_MODEL`, `JEV_DECISIONS_URL`...) |
| `prompts/system.md` | System prompt vai trò Report |
| `prompts/compact.md` | Prompt tóm tắt lịch sử hội thoại (memory rolling) |
| `tests/test_agent.py`, `tests/test_judge.py` | Test hành vi graph + judge (fake model/MCP/judge, không gọi mạng) |

Khác biệt lớn nhất so với Data Agent (cùng team, `agents/data/`): Report dùng
`langchain_openai.ChatOpenAI` + LangGraph, không dùng LiteLLM thuần. Đây là framework riêng của
Report trong 3 agent của team AGENT_A.

Dependency chính (`agents/report/pyproject.toml`): `langgraph>=1.2`, `langchain-openai>=1.6`,
`httpx`, `mcp`, `vdagent-sdk`.

## 2. Hai chế độ vận hành và luồng xử lý

Report Agent hỗ trợ hai chế độ theo [spec.md](spec.md):

1. **StepSpec@1 `draft_report` (Orchestrator)**: Chạy tất định, offline qua `stepspec.py` và `compose.py` mà không cần LLM hay Jev judge. Đọc các artifact đầu vào đã ghim hash (`insight`, `comparison`, `peer_definition`, `chart_spec`), kiểm chứng toàn bộ statement số liệu và chart bindings, gọi `save_report` để lưu markdown và `artifact_put` để lưu artifact `report@1`.
2. **Direct Chat (Hỏi đáp & Giải thích)**: Khi nhận tin nhắn tự do (không phải `ContractMessage`), nếu `REPORT_LLM=off` sẽ trả về `AgentReport@1` `state: rejected` với mã `LLM_REQUIRED`. Khi có LLM, chạy qua `LangGraphAgent` với cờ `direct_chat=True`:
   - Mở MCP session (`open_mcp_session`).
   - Lọc tool chỉ gồm các tool hỏi đáp được phép (`ALLOWED_DIRECT_CHAT_TOOLS`: `describe_dataset`, `get_dataset_rows`, `artifact_get`). Không cung cấp và không cho phép `send_to_agent`, `create_chart`, `save_report`.
   - Kiểm soát tham số tool: giới hạn `artifact_id` và `dataset_id` về các ID đã hiện diện trong ngữ cảnh (lịch sử, tóm tắt hoặc phát hiện trong lượt).
   - Chạy graph LangGraph, qua Jev quality gate dùng tiêu chí grounded QA (không đòi chart/report ID hay số liệu khi nguồn không có). Nếu Jev không khả dụng, vẫn trả lời nhưng đánh dấu `partial` cùng warning `QUALITY_GATE_UNAVAILABLE`; nếu draft bị từ chối sau lần sửa, trả `rejected` mà không phát draft đó.
   - Đầu ra cuối tại node `finalize` được đóng gói thành envelope `AgentReport@1` chuẩn; câu trả lời đạt gate dùng `state: completed`, còn draft bị Jev từ chối sau lần sửa dùng `state: rejected` kèm error. Direct chat hiện không tạo artifact nên `artifact_refs: []`.

## 3. Graph (`graph.py`) — các node

```
agent ──tool calls──▶ tools ──▶ agent
agent ──text draft──▶ assess ──pass──▶ finalize
                      assess ──reject, budget left──▶ revise ──▶ agent   (tối đa 1 lần)
                      assess ──reject, hết budget──▶ finalize
```

- **`agent`**: gọi model (`bind_tools` nếu còn tool và chưa tới bước cuối). Nếu là bước cuối
  (`steps >= ctx.max_steps`) mà model vẫn cố gọi tool, câu trả lời bị ép thành
  `STEP_LIMIT_TEXT = "[step limit reached before I could finish; no further tool calls were made]"`
  (hoặc giữ text đã có nếu model đã trả lời). Nếu model trả tool call, các bước gọi tool được báo
  qua `ctx.emit_assistant(reply.text, calls)` ngay lập tức (R2/R3 — streaming từng bước tool).
- **`tools`**: chạy song song (`asyncio.TaskGroup`) mọi tool call đang chờ; mỗi kết quả được báo
  qua `ctx.emit_tool_result` ngay khi xong. Artifact ID (`ds_/ch_/rp_` + `\w+`, regex
  `ARTIFACT_ID = re.compile(r"\b(?:ds|ch|rp)_\w+")`) được trích từ nội dung tool result và tích
  luỹ vào `state["artifacts"]` (không trùng lặp).
- **`assess`**: chỉ chạy khi model trả một draft text (không tool call). Gọi
  `judge.assess(request, draft, artifacts)` với `request` = nội dung tin nhắn cuối trong
  `ctx.history` (tin gửi tới Report ở turn này).
- **`after_assess`**: nếu `verdict.passed` → `finalize`. Nếu bị từ chối **và** chưa từng revise
  (`revisions == 0`) **và** còn budget bước (`steps < ctx.max_steps`) → `revise`. Ngược lại →
  `finalize` (chấp nhận draft hiện tại dù bị từ chối, vì đã hết lượt sửa).
- **`revise`**: thêm draft cũ (AIMessage) + review của Jev (HumanMessage
  `"[reviewer] {verdict.review}"`) vào `messages`, tăng `revisions`, quay lại `agent`.
- **`finalize`**: `ctx.emit_assistant(draft)` — đây là **lần duy nhất** câu trả lời cuối được gửi
  ra ngoài (Backend/Orchestrator chỉ thấy draft này, không thấy các draft bị từ chối hay nội dung
  review).

Kết luận quan trọng: **tối đa một lần revise mỗi turn**, bất kể verdict lần 2 pass hay fail —
`after_assess` chỉ cho phép `revise` khi `state.get("revisions", 0) == 0`.

## 4. Jev quality gate (`judge.py`)

- Jev là model "System One" của TypeSafe, phục vụ qua **decisions endpoint** của OpenRouter
  (`https://openrouter.ai/api/alpha/decisions` mặc định, cấu hình qua `JEV_DECISIONS_URL`), không
  phải `chat/completions` thông thường. Model mặc định: `typesafe/jev-1.13` (`DEFAULT_JUDGE_MODEL`
  trong `settings.py`, override qua `JUDGE_MODEL`).
- Request gửi `state = {request, answer, artifacts}` và hai câu hỏi kiểu "typed decision":
  - `acceptable` (type `noul`): xác suất draft chấp nhận được, ngưỡng pass là
    `PASS_THRESHOLD = 0.5` (`>=` là pass).
  - `problem` (type `choice`): vấn đề chính nếu không đạt — một trong
    `none | missing_part | unsupported_claim | no_numbers | unclear`.
- Mỗi `problem` map sang một review message cố định (`REVIEW` dict) được đưa lại cho model ở bước
  `revise`, ví dụ `missing_part` → "Cover every part of it, creating any missing chart or report."
- **Jev lỗi (HTTP error, JSON hỏng, thiếu field, timeout 10s) luôn được coi là PASS**
  (`Verdict(acceptable=None, problem=None)`, và `Verdict.passed` trả `True` khi `acceptable is
  None`). Lý do ghi ngay trong docstring: "an unusable reply ... counts as a pass: a judge outage
  must never block an answer." Draft không bao giờ bị Jev chặn vô thời hạn vì backend judge sập.
- Test `test_an_unusable_jev_reply_counts_as_a_pass` phủ 5 case: lỗi HTTP 500, thiếu `answers`,
  `noul` không phải số, JSON hỏng, timeout — tất cả đều pass.

## 5. Tool MCP thật sự Report gọi được

Theo permission matrix `backend/vdagent_backend/mcp/tools.py` (`PERMISSIONS`), agent `report`
được cấp:

| Tool | Việc |
| --- | --- |
| `describe_dataset` | Cột, row count, min/max/null-count của một dataset (ALL_AGENTS) |
| `get_dataset_rows` | Đọc một trang dữ liệu dataset (ALL_AGENTS) |
| `create_chart` | **Chỉ report** — dựng chart Vega-Lite từ dataset, trả `{chart_id, embed}` |
| `save_report` | **Chỉ report** — lưu markdown report, trả `report_id`; validate mọi
  `{{chart:ch_…}}` / `{{dataset:ds_…}}` nhúng trong markdown phải là ID đã tồn tại (`_save_report`
  raise lỗi `markdown references unknown ids` nếu không) |
| `artifact_put/get/list`, `get_user_context` | ALL_AGENTS, dùng chung |

Report **không** có `run_query`, `list_tables`, `describe_table` (chỉ `data`) — khớp với
`prompts/system.md`: "You do not run new analysis; work from the provided findings and dataset
ids."

## 6. Trích dẫn artifact — bằng chứng trong prompt/code

`prompts/system.md` (mục "Writing the report" và "Your reply") nêu rõ, khớp với nguyên tắc
"trích dẫn artifact ID" từng đề cập ở `task-contract-v0.1.md`:

- Nhúng artifact bằng placeholder trên dòng riêng: `{{chart:ch_…}}`, `{{dataset:ds_…}}` — viewer
  render tại chỗ.
- "Use only ids you actually received or created; never invent ids." — không tự bịa ID.
- Câu trả lời cuối (`Your reply`) phải tự chứa: `report_id`, tiêu đề, các `chart_id` đã tạo kèm
  một dòng mô tả mỗi cái, và một đoạn tóm tắt kết luận của report.

Jev judge còn thực thi lại đúng nguyên tắc này ở tầng khác: câu hỏi `acceptable` yêu cầu draft
"cites the chart/report ids from `artifacts` it created"; vấn đề `unsupported_claim` là "cites ids
not in `artifacts` or states numbers nothing in the turn backs" — tức là việc không bịa ID được
kiểm hai lớp: prompt (lớp 1, không phải guardrail) + Jev quality gate (lớp 2, có thể chặn draft
thật sự, dù tối đa 1 lần revise).

Việc **chỉ lưu report khi người dùng yêu cầu** (nêu trong `docs/agent-a/report/README.md` và
`task-contract-v0.1.md`) **không thấy bằng chứng rõ ràng nào trong `prompts/system.md` hiện tại**
— `system.md` mô tả `save_report` như một tool luôn dùng để "Turn the findings ... into a clear,
well-structured markdown report ... and save it", không có điều kiện "chỉ khi user yêu cầu".
Không có guardrail code nào trong `graph.py`/`judge.py` chặn việc gọi `save_report` một cách có
điều kiện — quyết định gọi hay không hoàn toàn nằm ở model, tức chỉ là "guardrail lớp 1" (prompt),
đúng như CODING_RULES.md cảnh báo. **Cần xác nhận lại với Orchestrator/team** nếu nguyên tắc này
vẫn phải giữ.

## 7. Fallback khi lỗi

Không có "fallback report" kiểu template tĩnh trong code Python hiện tại (khác với
`createFallbackReport` từng có trong `src/agents/analytics.ts` ở kiến trúc TypeScript cũ — file đó
không còn áp dụng cho Report, vì Report giờ là package Python riêng, không dùng chung
`analytics.ts`). Các đường lỗi thực tế trong `agent.py`/`graph.py`/`mcp_client.py`:

- Model timeout (`asyncio.timeout` hết hạn hoặc `openai.APITimeoutError`) → raise
  `AgentTimeoutError`, không nuốt lỗi bằng fallback (khớp `context.signal`/không nuốt lỗi trong
  CODING_RULES.md, dù ở đây là timeout riêng của Report chứ không phải `signal.aborted` kiểu cũ).
- Lỗi khác từ model (`RuntimeError`, provider 5xx...) propagate nguyên vẹn — test
  `test_model_timeout_is_agent_timeout_and_other_failures_propagate` xác nhận.
- Lỗi tool MCP (timeout 30s, exception transport, `is_error` từ MCP) không làm turn crash: biến
  thành `error: ...` text trả về cho model như một `ToolMessage` bình thường, model tự quyết định
  làm gì tiếp (`run_mcp_tool` trong `mcp_client.py`).
- Jev lỗi → coi như pass (mục 4) — đây là "fallback" thật sự duy nhất trong Report: fallback của
  quality gate, không phải fallback của report content.

## 8. Bộ nhớ / compaction

`LangGraphAgent.compact(previous_summary, messages)` dùng `prompts/compact.md`, gọi model một lần
(không qua graph, không qua Jev) để gộp summary cũ + message mới thành summary mới (giữ nguyên
id, artifact, giới hạn không ghi rõ số từ trong code — số từ nằm trong `compact.md`). Không liên
quan tới `sanitizeFinalAnswer` (đó là hàm của Orchestrator trong `analytics.ts`, không áp dụng
cho Report).

## 9. Điều đã chốt theo spec.md (30/09/2026)

- Contract runtime chính thức cho Orchestrator là `StepSpec@1` operation `draft_report`, catalog `contracts/vdagent_contracts/catalogs/report.json` và artifact `report@1` (WS6). `task-contract-v0.1.md` là tài liệu draft cũ, không dùng làm contract runtime.
- Phản hồi worker ở cả hai chế độ (StepSpec và direct chat) đều chuẩn hóa theo `AgentReport@1` envelope (`render_agent_report`).
- Trực quan hóa và Dashboard/PDF: Report Agent embed biểu đồ qua `{{chart_spec:...}}` và xuất artifact `report@1` cùng markdown; việc render PDF và Dashboard thuộc trách nhiệm phối hợp của Backend/Frontend. Chi tiết triển khai xem tại [spec.md](spec.md).
