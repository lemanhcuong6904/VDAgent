# VDAgent — Data Agent: thiết kế kỹ thuật (v5, khớp code)

Sep 30, 2026 · viết lại sau khi nhánh `main` xóa bỏ kiến trúc pipeline S0–S7 cũ và thay bằng một
Python plugin mỏng.

## 0. Bản này thay bản v4 thế nào

Bản v4 trước đó (còn trong lịch sử Git của file này) mô tả một kiến trúc cho **một domain khác**
(bất động sản: "phân khu", "căn hộ", peer comparison) với pipeline tất định 8 bước S0→S7, semantic
layer (`semantic/`), value index, ba tầng sinh SQL T1/T2/T3, catalog sinh tự động từ DDL, và một
contract điều khiển/dữ liệu rất chi tiết (DISPATCH/START/REWIRE/RELEASE/CANCEL/ANSWER, snapshot
ghim theo run, mã lỗi riêng...). Toàn bộ phần đó **không còn tồn tại trong code**: các file
tương ứng (`budgets.py`, `catalog.py`, `context.py`, `operations.py`, `specs.py`, `pipeline/*`,
`semantic/*`, `sql/compile_t1.py`, `sql/templates_t2.py`, `sql/t3.py`, `eval/*`) đã bị xóa khỏi
`agents/data/vdagent_data/` trong một refactor trên `main`. Đây không phải một lần "vá" tài liệu
cho khớp — kiến trúc mới là một lựa chọn khác hẳn (agentic tool-calling loop thay vì workflow tất
định nhiều bước), nên tài liệu dưới đây viết lại từ đầu theo đúng những gì code làm.

Điều còn giữ được từ v4: vai trò nghiệp vụ ("Data Agent là agent duy nhất đọc Data Warehouse",
"Data không diễn giải kết quả, không nói trực tiếp với người dùng") và vị trí trong hệ agent. Domain
dữ liệu thực tế trong code hiện tại cũng khác v4 (kho bán lẻ, không phải bất động sản) — xem mục 4.

## 1. Nhiệm vụ

Data Agent là một trong năm agent cộng tác của VDaAgent (`orchestrator`, `data`, `compare`,
`insight`, `report`). Nó là **agent duy nhất có tool đọc trực tiếp Data Warehouse** (`list_tables`,
`describe_table`, `run_query`). Việc của nó: nhận một yêu cầu dữ liệu (từ user qua orchestrator,
hoặc từ một agent khác qua `send_to_agent`), viết SQL đúng, và trả về **dataset id** cùng mô tả đủ
để agent khác hoặc người dùng dùng lại mà không cần đọc SQL. Nó không diễn giải xu hướng, không đưa
ra kết luận nghiệp vụ — đó là việc của `insight`.

## 2. Kiến trúc: tool-calling loop mỏng qua LiteLLM + MCP

Không còn pipeline nhiều bước với state object tất định. Toàn bộ agent là **một vòng lặp
tool-calling** giao cho LLM tự quyết định gọi tool nào, bao nhiêu lần, theo thứ tự nào — trong giới
hạn `max_steps` do runtime cấp cho mỗi lượt gọi (`InvocationContext.max_steps`). File chính:
`agents/data/vdagent_data/agent.py` (206 dòng).

```
invoke(ctx):
  mở một MCP session (bearer token của ctx.mcp)
  liệt kê tool MCP mà server cấp cho agent "data" (trừ send_to_agent)
  nếu ctx.peers khác rỗng: thêm tool send_to_agent (gọi agent khác, chờ trả lời)
  messages = [system prompt (+ tóm tắt hội thoại cũ nếu có), *ctx.history]
  lặp step = 1..ctx.max_steps:
      tool_choice = "none" nếu là step cuối, ngược lại "auto"
      gọi LLM (LiteLLM) với messages + tools + tool_choice
      nếu là step cuối mà model vẫn trả tool_calls (bỏ qua tool_choice="none"):
          không còn lượt để chạy tool đó -> thay bằng nội dung rỗng hoặc
          STEP_LIMIT_TEXT ("[step limit reached before I could finish...]")
      report step qua ctx.emit_assistant(content, tool_calls)
      nếu không có tool_calls: kết thúc lượt (đây là câu trả lời cuối)
      chạy mọi tool_calls của step đó SONG SONG (asyncio.TaskGroup)
      mỗi kết quả tool được report qua ctx.emit_tool_result rồi thêm vào messages
```

Không còn khái niệm "tầng sinh SQL T1/T2/T3" hay "S0 kiểm phiếu tất định" — model tự viết SQL trực
tiếp trong mỗi lần gọi `run_query`/`query_datasets`, không có bước biên dịch từ semantic layer riêng.
Mọi ràng buộc cứng (SELECT-only, timeout, giới hạn dòng, lọc quyền) nằm ở **phía backend/MCP**
(`backend/vdagent_backend/mcp/sql.py`, `tools.py`), không phải trong code của agent.

### 2.1. `LiteLLMAgent` và `_Turn`

- `LiteLLMAgent` (agent.py:85) implements `Agent` protocol của `vdagent_sdk`: `invoke(ctx)` chạy
  một lượt, `compact(previous_summary, messages)` nén lịch sử cũ (mục 2.4).
- Một `LiteLLMAgent` phục vụ nhiều lượt gọi đồng thời; state của một lượt (`_mcp_tool_names`, MCP
  session) sống trong đối tượng `_Turn` riêng tạo mỗi lần `invoke`, không lưu trên `self`.
- `send_to_agent_tool(peers)` (agent.py:42) build schema OpenAI function-calling cho tool đặc biệt
  `send_to_agent`: liệt kê tên + mô tả từng peer, model chọn `agent` (enum đúng tên peer) và viết
  `message` tự chứa đủ ngữ cảnh (kể cả dataset id cần thiết) vì message đó gửi cho agent khác, không
  kèm lịch sử hội thoại hiện tại.
- Dispatch tool call (`_Turn._tool_content`, agent.py:174): nếu tên là `send_to_agent` và có peer ->
  gọi `ctx.call_agent`; nếu tên nằm trong danh sách tool MCP đã liệt kê -> `run_mcp_tool`; ngoài ra
  trả `error: unknown tool '<name>'`. JSON arguments hỏng hoặc không phải object cũng trả `error:
  ...` cho model tự sửa ở lượt sau, không throw.

### 2.2. `max_steps` và bước cuối

`max_steps` do runtime cấp qua `ctx`, không phải hằng số trong code của agent (khác v4, nơi "ngân
sách bước" là tham số cấu hình catalog cứng — ở đây nó do bên gọi `invoke` quyết định mỗi lượt).
Bước cuối luôn gọi LLM với `tool_choice="none"` để ép model trả lời bằng văn bản; nếu model vẫn cố
gọi tool ở bước đó, các tool_calls bị bỏ (không có lượt nào chạy chúng) và agent trả
`STEP_LIMIT_TEXT` thay cho nội dung rỗng.

### 2.3. Timeout

Hai tầng timeout độc lập, không có "đồng hồ hạn giờ theo run" chung như v4:

| Tầng | Giá trị | Nguồn | Khi vượt |
| --- | --- | --- | --- |
| Một lần gọi LLM | `LLM_TIMEOUT_S` (mặc định 120s) | `.env` của plugin (mục 5) | `LLMTimeoutError` → agent ném lại thành `AgentTimeoutError` (SDK) |
| Một lần gọi tool MCP | 30s cố định (`MCP_TOOL_TIMEOUT_S`, mcp_client.py:22) | hằng số trong code | trả `error: tool '<name>' timed out after 30s` cho model, KHÔNG throw — lượt vẫn tiếp tục |

Kết quả tool MCP bị cắt ở 16 000 ký tự (`MAX_TOOL_RESULT_CHARS`, mcp_client.py:23), thêm hậu tố
`…[truncated]`, trước khi đưa vào `messages` gửi cho model.

### 2.4. Nén hội thoại (`compact`)

Không còn "bản ghi ghim theo run" hay snapshot khóa cứng. Bộ nhớ dài hạn của agent là một **tóm
tắt dạng văn bản** do chính agent (qua LLM, dùng `compact_prompt`) tự viết lại mỗi khi runtime gọi
`compact(previous_summary, messages)`:

- `render_for_compaction` (agent.py:67) format các message thành dòng `[inbound] …` (user hoặc
  agent khác gửi tới), `[you] …` (agent tự nói), `[you called <tool>] <args>` (tool call), `[tool
  result] …` (kết quả tool, cắt ở 2 000 ký tự — `COMPACT_TOOL_TEXT_CHARS`) — cùng tóm tắt trước đó.
- `compact_prompt` (`prompts/compact.md`) yêu cầu model giữ tối đa 400 từ, ưu tiên: sở thích/quy
  ước người dùng, câu hỏi–trả lời đã có, **id artifact** (`ds_…`, `ch_…`, `rp_…`) kèm mô tả một
  dòng, và vấn đề chưa giải quyết; không được bịa id hay số liệu.
- Lượt gọi tiếp theo build system prompt bằng `build_system_prompt(prompt, ctx.summary)`
  (agent.py:36): nếu có tóm tắt, nối thêm heading `## Summary of earlier work with this user` +
  nội dung tóm tắt vào cuối system prompt gốc.

## 3. MCP: tool nào Data Agent thực sự gọi được

Nguồn sự thật là `backend/vdagent_backend/mcp/tools.py` (`PERMISSIONS` — ma trận quyền theo agent),
không phải mô tả trong system prompt. Với agent `data`:

| Tool | Việc gì | Ghi chú |
| --- | --- | --- |
| `list_tables` | Liệt kê bảng warehouse + số dòng | Chỉ `data` được gọi (không chia sẻ với agent khác) |
| `describe_table` | Cột, kiểu, 5 dòng mẫu của một bảng | Chỉ `data` |
| `run_query` | Chạy một `SELECT`/`WITH … SELECT` trên warehouse, lưu kết quả thành **dataset mới**, trả `dataset_id` + cột + `row_count` + `truncated` + `preview` (20 dòng đầu). Timeout 10s, cắt ở 10 000 dòng | Chỉ `data` |
| `describe_dataset` | Cột, row_count, min/max/null từng cột của một dataset đã có | Mọi agent (`ALL_AGENTS`) |
| `get_dataset_rows` | Đọc một trang dữ liệu của dataset (tối đa 200 dòng/lần) | Mọi agent |
| `query_datasets` | Chạy SQL nối nhiều dataset đã có (mỗi dataset là một bảng tên theo id, vd `"ds_…"`), lưu thành dataset mới | Chia sẻ với `compare`, `insight` |
| `get_user_context` | user_id, role, authorized_scope | Mọi agent |
| `artifact_put`/`get`/`list` | Đọc/ghi artifact envelope theo run; `data` chỉ được ghi các loại `data_package`, `metric`, `dq`, `dataset` (`WRITABLE_TYPES`) | Mọi agent đọc; ghi theo loại sở hữu |
| `re_list_tables`/`re_describe_table`/`re_run_query` | Biến thể "real-estate DW" (mock) của ba tool đầu, có lọc theo `authorized_scope` của user | Chỉ `data` |

Ghi chú: `prompts/system.md` hiện tại chỉ mô tả cho model sáu tool đầu (`list_tables`,
`describe_table`, `run_query`, `query_datasets`, `describe_dataset`, `get_dataset_rows`) gắn với
domain kho bán lẻ — không nhắc tới `get_user_context`, `artifact_*` hay bộ `re_*`. Đây là quan sát
từ việc đọc code, không phải điều cần "sửa cho khớp" trong phạm vi tài liệu hóa này; nếu prompt cần
mô tả thêm các tool đó thì đó là thay đổi hành vi, thuộc quyết định của owner `data` kèm test theo
`CODING_RULES.md`.

Việc thực thi SQL, ràng buộc SELECT-only, whitelist bảng/cột, chèn filter quyền... nằm hoàn toàn ở
backend (`backend/vdagent_backend/mcp/sql.py`, `tools.py`) — agent Python không tự kiểm tra SQL, nó
chỉ nhận lỗi dạng text (`error: …`) khi backend từ chối.

## 4. System prompt và domain dữ liệu hiện tại

`prompts/system.md` mô tả cho model một **kho bán lẻ** (retail sales warehouse), khác hẳn domain
bất động sản của tài liệu v4 cũ:

- Vai trò 5 agent, quy ước đọc message: `[from: user]` (người dùng viết trực tiếp) và
  `[from: <agent>]` (agent khác gọi qua `send_to_agent`; câu trả lời cuối được trả nguyên văn làm
  kết quả tool cho agent đó, nên phải tự chứa đủ nghĩa).
- Schema star schema SQLite: `fact_sales` (grain một dòng/lượt bán), `dim_date`, `dim_product`,
  `dim_store`; công thức `revenue`/`cost`/`margin`; mẹo dialect SQLite (không có `YEAR()`, chia
  nguyên bị truncate, dùng `strftime`, `ROUND`, window function được hỗ trợ).
- Ràng buộc nghiệp vụ nêu trong prompt (không phải guardrail thực thi trong code — theo
  `CODING_RULES.md`, ràng buộc quan trọng phải nằm trong code có test, prompt chỉ là lớp thứ hai):
  không dán bulk rows, luôn cho id dataset + grain + cột + filter + row count, không diễn giải xu
  hướng.

`prompts/compact.md` là system prompt riêng dùng khi gọi `compact()` (mục 2.4), không liên quan
domain — chỉ hướng dẫn cách tóm tắt.

## 5. Cấu hình

`agents/data/vdagent_data/settings.py`: đọc `.env` của riêng plugin này
(`agents/data/.env`, mẫu ở `agents/data/.env.example`) đè lên process environment bằng
`dotenv_values()` — **không** ghi vào `os.environ` (quy tắc SDK R11, vì nhiều plugin share chung một
process Backend).

| Biến | Bắt buộc | Ý nghĩa |
| --- | --- | --- |
| `OPENAI_API_KEY` | Có | Khóa cho endpoint OpenAI-compatible |
| `OPENAI_BASE_URL` | Có | Base URL endpoint (model phải hỗ trợ tool calling) |
| `LLM_MODEL` | Có | Tên model, LiteLLM gọi với prefix `openai/<model>` |
| `LLM_TIMEOUT_S` | Không | Mặc định 120s; phải là số dương |

Thiếu biến bắt buộc hoặc `LLM_TIMEOUT_S` không hợp lệ → `PluginConfigError` nêu rõ tên biến, ném ra
ngay khi `build_agent()` chạy lúc Backend khởi động plugin — không phải lỗi runtime khi xử lý yêu
cầu.

## 6. Test hiện có

`agents/data/vdagent_data/tests/test_agent.py` (test bằng `pytest`, LLM và MCP đều là fake/scripted
— không gọi mạng thật):

- Plugin entry: `setup()` đăng ký đúng agent từ env plugin; thiếu biến báo đúng tên; `read_env` ưu
  tiên file `.env` và không ghi `os.environ`.
- Tool loop: dừng đúng ở `max_steps` với `tool_choice="none"` ở bước cuối; nhiều `send_to_agent`
  trong cùng step chờ độc lập từng câu trả lời (không serial); kết quả MCP được emit và bị cắt ở
  giới hạn ký tự; lỗi tool (exception, `is_error=True`, JSON hỏng, tool không tồn tại, thiếu tham
  số `send_to_agent`) đều biến thành nội dung `error: …` cho model, lượt không bị crash; `LLMTimeoutError`
  thành `AgentTimeoutError`, lỗi khác (vd `RuntimeError`) truyền nguyên vẹn ra ngoài.
- Nén hội thoại: `compact()` dùng đúng `compact_prompt`, `tool_choice="none"`, ghép tóm tắt cũ +
  message mới, cắt tool result dài; timeout khi nén cũng thành `AgentTimeoutError`.

Không còn test cho semantic layer, SQL compiler, catalog hay state machine S0–S7 vì các module đó
đã bị xóa cùng code.

## 7. Việc còn để ngỏ (quan sát khi đọc code, không phải quyết định của tài liệu này)

- System prompt chưa mô tả `get_user_context`, `artifact_*`, `re_*` dù MCP đã cấp quyền — cần owner
  `data` xác nhận đây là cố ý (chưa dùng trong luồng hiện tại) hay thiếu sót.
- Không có tài liệu nào (kể cả bản v4 cũ) mô tả domain "kho bán lẻ" hiện có trong `system.md` —
  không rõ quyết định đổi domain từ bất động sản sang bán lẻ được ghi ở đâu; nên hỏi người quyết
  định kiến trúc (commit `b2eccd2`, `chore: sync data/orchestrator agents and refactor docs for team
  debugging`) nếu cần biết lý do.
