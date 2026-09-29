# Orchestrator Agent — thiết kế v4 (khớp code hiện tại)

Cập nhật 30/09/2026, viết lại từ code thật ở `agents/orchestrator/vdagent_orchestrator/` sau khi
xác nhận tài liệu cũ (`docs/agent-a/*` bản TypeScript) đã lỗi thời — xem quyết định trong
`docs/refactor/PLAN.md` mục 0.2 và mục 1: nguồn sự thật cho kiến trúc hiện hành là
`docs/superpowers/specs/*.md` + code, không phải `docs/agent-a/*` cũ. Tài liệu này chỉ mô tả lại
đúng cơ chế đang chạy, không phải một đề xuất mới.

Docstring đầu `agent.py`: "Orchestrator v4 trên SDK; D3 centralized waves; DEC-025 turn-based
questions". Các mã `DEC-xxx`, `R1…R11`, `INT-x`, `PLN-x`... rải trong code là số hiệu quyết định/
quy tắc của spec `docs/superpowers/specs/*.md`; tài liệu này không giải nghĩa lại từng mã, chỉ mô
tả luồng.

## 1. Package và ngôn ngữ

- Python, package `agents/orchestrator/vdagent_orchestrator/`. Không phải TypeScript, không phải
  `src/agents/orchestrator/index.ts` (đường dẫn đó không tồn tại trong repo hiện tại).
- Là một Backend plugin theo khuôn `agents/_template`: export `setup(api, opts)`;
  `build_agent(env)` dựng `OrchestratorAgent`.
- Phụ thuộc chính (`pyproject.toml`): `vdagent-sdk`, `vdagent-contracts` (StepSpec, AgentReport,
  catalog, envelope — package `contracts/`), `vdagent-agentkit` (LLM router, MCP client, settings —
  `agents/_shared/`), `litellm`, `mcp`, `jsonschema`.
- Chạy trong tiến trình Backend (không phải service riêng): Backend nạp khi
  `vdagent_orchestrator` có trong `plugins:` của `backend/config.yaml`.

## 2. Gọi specialist: `send_to_agent`, không phải `agents.delegate`

Docs cũ mô tả tool `agents.delegate` (kiến trúc TypeScript cũ). Code hiện tại **không có** tool đó.
Orchestrator gọi các agent khác qua `ctx.call_agent(...)`, phát sinh từ `ToolCall` tên
`SEND_TO_AGENT` (`agent.py` lớp `CtxSender.send`, dòng 56-75). Nội dung gửi đi là một `StepSpec@1`
(JSON, định nghĩa ở `contracts/vdagent_contracts/messages.py`), không phải message theo 9 loại của
`contract-v1.0.md` (`DISPATCH`/`START`/`REWIRE`/...).

`StepSpec` mang: `run_id`, `plan_id`, `step_id` (dạng `B<n>`), `idempotency_key` (`plan_id:step_id`),
`operation`, `spec` (phiếu giao việc), `user_context`, `snapshot_id`, `input_refs`
(`ArtifactRef` của các bước upstream đã hoàn tất), `released_inputs`, `answered_choices`,
`deadline_s`, `original_question`. Dựng bởi `dispatcher._outbound` gọi
`planning.step_spec(...)`.

Ghi chú quan trọng: repo có sẵn `control/models.py` và `control/rules.py`, implement gần đúng
giao thức 9-message/3-response của `contract-v1.0.md` (header 10 trường, `DISPATCH`, `REPORT`,
`receive_report`...). Nhưng `agent.py` **không import hay gọi** hai module này — chỉ các test riêng
của chúng (`tests/test_control_models.py`, `tests/test_control_rules.py`) dùng tới. Đây là code
còn tồn tại trong repo nhưng không nằm trên đường chạy thật của một turn; đừng nhầm là contract
đang dùng.

## 3. Một turn (`OrchestratorAgent.invoke`)

1. Lấy tin nhắn cuối từ `ctx.history`, bỏ tiền tố `[from: ...]`.
2. `load_state(ctx.memory)` — đọc `ConversationState` (run hiện tại + đang chờ gì) từ note kiểu
   `run_state` trong `ctx.memory` (`run_state.py`).
3. Mở phiên MCP (`self._mcp(ctx.mcp.url, ctx.mcp.token)`), tạo `_Turn`, chạy `turn.run(text)`.
4. `save_state` ghi lại `ConversationState`, `ctx.emit_assistant(reply)` trả câu trả lời.
5. `compact()`: không tóm tắt thêm gì — toàn bộ state của run nằm trong memory (R1), không cần
   compact hội thoại riêng.

### 3.1. Routing tin nhắn (`run_state.route_message`)

Suy ra route từ `ConversationState.awaiting` (đang chờ CLARIFY / AGENT_QUESTION / DECISION) và
`state.run`:

| Route | Điều kiện | Xử lý |
|---|---|---|
| `NEW_QUESTION` | Không chờ gì, và (chưa có run hoặc run đã xong) | Reset state, hiểu câu hỏi mới từ đầu |
| `CONTINUE` | Không chờ gì nhưng run cũ chưa xong (hết wave budget lượt trước) | Chạy tiếp run cũ với bất kỳ tin nhắn nào |
| `CLARIFY_ANSWER` | Đang chờ CLARIFY | Ghép câu trả lời vào, hiểu lại câu hỏi gốc |
| `ANSWER` | Đang chờ AGENT_QUESTION | Khớp lựa chọn với thẻ câu hỏi agent (`inputs.answer`) |
| `DECISION_ANSWER` | Đang chờ DECISION | Khớp lựa chọn với decision card (`decision.answer_decision`) |

Một tin nhắn tới khi không chờ gì luôn là câu hỏi mới (tương đương H9 trong spec).

### 3.2. Câu hỏi mới → `_question`

1. `understand()` (llm1.py, gọi LLM 1) → `IntentDraft`. Nếu LLM không dùng được
   (`understood.draft is None`) → trả `failure_text("LLM_UNAVAILABLE")` ngay (không rơi vào
   SIMPLE_ROUTER ở bước này — SIMPLE_ROUTER được gọi bên trong `understand`/`llm1.py`, không phải
   ở `agent.py`).
2. `intent.decide(...)` áp luật A1–A6 (xem `intent.py`):
   - A1 `scope_check == OFF_TOPIC` → REJECT, kèm câu giải thích phạm vi hệ thống trả lời.
   - A2 `scope_check == DECISION_REQUEST` → REJECT (hệ thống không quyết định thay người dùng).
   - A3 mọi `task_kinds` đều không được agent nào phục vụ (`served`) → REJECT.
   - A4/A5 thiếu đối tượng (`mentions`) hoặc thiếu nhu cầu (`metrics`/`phenomena`/`task_kinds`) →
     ASK (tối đa `MAX_CLARIFY_ROUNDS = 2` vòng hỏi lại).
   - A6 hỏi lại đủ số vòng vẫn thiếu → REJECT.
   - Qua hết → PROCEED, dựng `IntentFrame` (đối tượng plan sẽ dùng), kèm `assumptions` cho phần
     chưa phục vụ được hoặc output mặc định.
3. `REJECT` → trả thẳng lý do (không tạo run). `ASK` → lưu `Awaiting(kind="CLARIFY", ...)`, trả câu
   hỏi làm rõ.
4. `PROCEED`: lấy `UserContext` qua tool MCP `get_user_context`; nếu lỗi → trả
   `failure_text("NO_USER_CONTEXT")`.
5. `planner.make_plan(...)` (mục 4 dưới) → có plan thì `records.new_run(...)` tạo `RunRecord`, ghi
   state, `put()` (lineage.py) neo run vào task hiện tại (artifact `run_state`), rồi chuyển sang
   `_advance`.

### 3.3. Vòng lặp điều phối (`_advance`)

```
while True:
    run = drive(run, ...)              # gửi wave, nhận reply, cập nhật step
    run = replan(run, ...)             # gộp mọi REPLAN đang chờ thành 1 lệnh LLM 2
    card = open_question(run)          # có câu hỏi agent nào cần hỏi Sales Ops?
    if card: lưu Awaiting(AGENT_QUESTION), trả thẻ, dừng turn
    if không còn gì ready hoặc hết wave budget của turn: break
decision = open_decision(run)          # có phần WRONG_RESULT cần hỏi "dùng tạm hay thử lại"?
if decision: lưu Awaiting(DECISION), trả thẻ, dừng turn
if run.finished: ghi run_summary (artifact), trả bản tóm tắt Markdown
else: trả CONTINUE_TEXT ("Còn phần đang xử lý. Gửi 'tiếp tục'...")
```

Ngân sách một turn: `CtxSender` chỉ còn `ctx.max_steps - 1` wave để gửi (bước cuối luôn dành cho
câu trả lời — R7); hết wave thì turn dừng nửa chừng và chờ tin nhắn tiếp theo để `CONTINUE`.

## 4. Wave-based dispatch (D3, `dispatcher.py`)

- `ready(run)`: mọi step `pending` mà toàn bộ `waits` đã thỏa (step nguồn `completed`, hoặc wait
  `SOFT` đã bị "release"), cộng thêm step `working` đã được đánh dấu `resend` (trả lời xong câu hỏi
  agent, gửi lại cùng idempotency key).
- Một **wave** = một lượt gọi `CtxSender.send`: một `emit_assistant` (báo đang chạy agent nào) kèm
  N `ToolCall` (`SEND_TO_AGENT`), N lệnh chạy đồng thời qua `asyncio.TaskGroup`, mỗi lệnh có
  `asyncio.timeout(item.timeout_s)` riêng (timeout → `TIMEOUT_REPLY = "error: TIMEOUT"`).
  `drive()` lặp gửi wave cho tới khi không còn gì `ready` hoặc hết `max_waves` của turn.
- Nhận reply (`_accept`): `TIMEOUT_REPLY`/`error:` → step failed; còn lại parse bằng
  `parse_agent_report` (contract `AgentReport`, `contracts/vdagent_contracts/reports.py`) và đối
  chiếu `run_id`/`step_id`/`idempotency_key`. Phân loại kết quả bằng `classify.classify(...)`:
  `DONE` (hoàn tất, có thể `partial` + `warnings`), `QUESTION` (agent hỏi lại — chỉ `data` và
  `compare` được phép, `ASKING_AGENTS` trong `control/rules.py`), hoặc lỗi (đi qua
  `_handle_error` → có thể `CANCEL`, `REPLAN` (tier 2), `DECISION` (tier 3, qua `escalate`), hoặc
  báo thẳng (`report_direct`) và lan (`propagate.py`) sang các step chờ nó.
- Data step đầu tiên hoàn tất "ghim" snapshot của cả run (`run.snapshot_id`); nếu nó lỗi trước,
  một step Data khác đang chờ được "release" để trở thành pin mới (logic trong `report_direct`).
- `maybe_close(run)`: đóng run đúng một lần khi mọi step đã ở trạng thái cuối, không còn gì
  `pending`, gọi `close.summarize(run)` để dựng `RunSummary`.

## 5. Catalog và understand/plan

- `catalogs.CatalogRegistry.load()` nạp catalog của mọi agent (`vdagent_contracts.catalogs.load_all`),
  cache theo version. Cung cấp: `operation(agent, name)`, `served_kinds()` (loại câu hỏi có agent
  phục vụ), `producers_of(kind)`, `vocabulary()` (metric/dimension/filter/attribute hợp lệ, lấy từ
  catalog của Data).
- `llm1.understand(...)`: gọi LLM 1 (qua `LlmRouter`) để ra `IntentDraft`; nếu LLM không sẵn sàng,
  rơi về `simple_router.route(...)` — chỉ nhận diện câu hỏi tra cứu đơn giản kiểu LOOKUP (có từ khóa
  số liệu như "bao nhiêu", "trung bình"... và tên một metric có trong catalog Data, không có từ khóa
  "quyết định"/"đề xuất"). Đây là **chế độ SIMPLE_ROUTER không cần LLM** nhắc ở `build_agent`.
- `planner.make_plan(...)`: gọi LLM 2 (`llm2.draft_plan`) ra `PlanDraft`, `planning.build_plan`
  dựng `Plan` (wiring các bước, `input_refs`), `checker.check(...)` áp 12 luật xác định (không
  LLM): mã bước hợp lệ, operation tồn tại trong catalog, spec khớp JSON Schema + từ vựng, wiring
  đúng loại dữ liệu cần, không có chu trình (`CYCLE`), output/task kind được phủ, tối thiểu một
  bước Data, không vượt `state.max_steps`... Nếu có vi phạm, thử sửa một lần (`PLN-3`, tối đa 2 lượt
  gọi LLM: draft + 1 correction); vẫn lỗi → `PLAN_REJECTED`. Nếu LLM 2 không dùng được và
  `allow_fallback=True` → `fallback.fallback_plan(...)` dựng kế hoạch tối thiểu không cần LLM.
- Ngân sách LLM một câu hỏi: `MAX_LLM_CALLS = 9` (`CallBudget`, tính cả hiểu câu hỏi, lập kế hoạch,
  mọi vòng clarify và mọi lần lên lại kế hoạch của cùng một run).

## 6. Replan (tier 2) và decision card (tier 3)

- **Tier 2 — `replan.py`**: mọi step được đánh dấu `awaiting_replan` trong turn được gộp thành
  **một** lệnh LLM 2 (`RPL-3`), tối đa `MAX_REPLANS = 2` lần lên lại kế hoạch mỗi run, mỗi phần chỉ
  được LLM thay thế một lần (`RPL-1`). Ngữ cảnh gửi cho LLM 2 chỉ gồm trạng thái/step, **không** gồm
  tóm tắt hay nội dung package (giữ nguyên tắc PLN-1). Kế hoạch mới được kiểm bằng 12 luật rồi áp
  dụng: step mới nối vào run, các step đang chờ step bị thay được "rewire" sang step mới, step bị
  bỏ (`drop`) chuyển `skipped`/gắn cờ `dropped`, step lỗi mà kế hoạch mới không xử lý được báo
  thẳng. Nếu LLM 2 không dùng được hoặc hết lượt replan → "bỏ" (`_abandon`): step `WRONG_RESULT`
  chuyển sang tier 3 nếu còn đủ điều kiện, các lớp lỗi khác báo thẳng.
- **Tier 3 — `decision.py`**: khi có step gắn cờ `awaiting_decision` (chỉ xảy ra khi lỗi
  `WRONG_RESULT` sau tier 2, xem `dispatcher.escalate`/`tier3_eligible`) và không còn gì khác đang
  chờ hoặc có thể chạy, Orchestrator gom chúng thành **một** decision card: "Dùng kết quả hiện có"
  hoặc "Thử lại phần …" cho từng step. Một run chỉ hỏi loại này một lần (`run.decision_asked`,
  DEC-025 — turn-based, không có timer hết hạn).
- **Câu hỏi của agent (`inputs.py`)**: khi Data/Compare trả `QUESTION`, Orchestrator hiển thị thẻ
  lựa chọn cho Sales Ops; tối đa `MAX_AGENT_QUESTIONS = 2` câu hỏi loại này mỗi run — câu thứ 3 huỷ
  luôn step đó (`TOO_MANY_QUESTIONS`) thay vì hỏi tiếp.

## 7. Đóng run (`close.py`)

- `close_status(run)`: `failed` nếu có step lỗi `DATA_QUALITY`, hoặc step Data chưa `completed`;
  `partial` nếu có step phân tích (Compare/Insight) chưa `completed`; `failed` nếu chỉ còn step
  output (Chart/Report) và chúng đều lỗi; `completed` (kèm lý do "thiếu báo cáo") nếu chỉ thiếu
  output; ngược lại `completed`/`OK`.
- `summarize(run)`: dựng `RunSummary` — trạng thái, lý do, danh sách phần thiếu (`MissingPart`, quy
  về step gốc gây lỗi qua `_root`, dùng câu tiếng Việt cố định từ `wording.py`, không LLM), output
  còn thiếu, phần bị drop, `task_kinds` chưa phục vụ được, cảnh báo, `assumptions`, coverage phân
  tích, `data_confidence`, danh sách package đã tạo.
- `render_markdown(summary)`: bản tóm tắt cuối gửi Sales Ops — kết quả, lý do, tóm tắt từng agent đã
  hoàn tất, phần thiếu, giả định, cảnh báo, và một khối `<details>` kỹ thuật (snapshot, version kế
  hoạch, số lần replan, coverage, mã lỗi) — mã bước/mã lỗi chỉ xuất hiện trong khối kỹ thuật này,
  không lẫn vào câu trả lời chính.

## 8. Wording tiếng Việt cố định (`wording.py`)

Không dùng LLM cho câu chữ hệ thống: tên phần hiển thị (`PART_NAMES`: Số liệu / So sánh với nhóm
tương đồng / Giải thích nguyên nhân / Biểu đồ / Báo cáo nháp), tiêu đề thẻ, nhãn nút "Thử lại",
câu "chưa có dữ liệu", câu "quá thời gian cho phép".

## 9. Những gì tài liệu cũ nói sai (so với code)

| Docs cũ (`contract-v1.0.md`, README cũ) | Thực tế code |
|---|---|
| Code ở `src/agents/orchestrator/index.ts`, TypeScript | `agents/orchestrator/vdagent_orchestrator/`, Python |
| Gọi specialist qua tool `agents.delegate` | Gọi qua `send_to_agent` (`ctx.call_agent`), StepSpec@1 JSON |
| Giao thức 9 loại message / 3 phản hồi (`DISPATCH`, `START`, `REWIRE`...) là đường dây thật | Đường dây thật là StepSpec/AgentReport (`contracts/vdagent_contracts/messages.py`, `reports.py`); `control/models.py`+`control/rules.py` implement gần đúng giao thức cũ nhưng **không được `agent.py` gọi** — chỉ có test riêng dùng |
| Không có `design.md` | File này |

## 10. Tham khảo thêm

- `agents/orchestrator/README.md` — README kỹ thuật ngắn của chính package (biến môi trường, cách
  chạy test `uv run pytest agents/orchestrator`).
- `docs/superpowers/specs/*.md` — spec kiến trúc gốc (invocation engine, turn rules R1–R11, agent
  plugin design) mà code hiện tại bám theo.
- `docs/refactor/PLAN.md`, `docs/refactor/HANDOFF.md` — quyết định 29/09/2026 coi `docs/agent-a/*`
  cũ là lỗi thời cho việc dẫn dắt code, và ghi lại đối chiếu code ↔ spec.
- Prompt LLM: `agents/orchestrator/vdagent_orchestrator/prompts/intent.md` (LLM 1),
  `prompts/plan.md` (LLM 2).
