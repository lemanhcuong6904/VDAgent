# Refactor tasks — 2026-09-29

> **Lưu ý (2026-10-04, Phase 5):** các file backend-v1 nhắc trong tài liệu này (`backend/vdagent_backend/engine/`,
> `events.py`, `backend/tests/test_engine.py`, …) đã bị gỡ; bản hiện hành là `runtime/engine.py`, `core/` và
> `backend/tests/runtime/`. Xem `AGENTS.md` §26.

Xem bối cảnh và nguồn sự thật trong [`PLAN.md`](PLAN.md). Đánh dấu `[x]` khi xong, thêm ngày +
commit ngắn. Không xoá task đã xong — để lại làm lịch sử.

## T0 — Xác nhận môi trường sạch (làm trước mọi task khác)

- [ ] `uv sync` chạy không lỗi.
- [ ] `uv run pytest` (toàn repo) pass.
- [ ] `cd frontend && npm install && npm test` pass.
- Nếu bất kỳ bước nào fail: dừng, ghi vào `HANDOFF.md` mục "Câu hỏi mở", không tiếp tục các task
  bên dưới cho tới khi rõ nguyên nhân (có thể là môi trường máy, không phải bug code).

## Backend / SDK

### T1 — Sửa format message lỗi ở nhánh exception nội bộ hiếm gặp của engine

- File: `backend/vdagent_backend/engine/engine.py`, hàm `_drive`, nhánh catch-all khoảng dòng
  386-388.
- Hiện tại: `f"internal error: {e}"` (chữ thường, không có tên exception type) khi bản thân
  `_execute` (bookkeeping của engine) raise lỗi ngoài dự kiến — khác với path lỗi từ plugin
  (`_failure`, dòng ~574-583) vốn đúng format `INTERNAL: <Type>: <detail>` theo
  `2026-09-26-agent-plugins-design.md` §5.4.
- Việc cần làm: đổi nhánh catch-all này dùng cùng format `INTERNAL: <Type>: <detail>` cho nhất
  quán, dễ debug khi engine tự lỗi. Đây là nhánh gần như không bao giờ chạm tới trong luồng bình
  thường (chỉ khi engine tự có bug) — rủi ro thấp, không đổi hành vi được test hiện tại phụ thuộc
  (kiểm tra `backend/tests/test_engine.py` trước khi sửa để chắc không có test nào assert đúng
  chuỗi cũ).
- Ưu tiên: thấp. Không chặn task khác.

### T2 — Dọn dead code `EventBus.broadcast()`

- File: `backend/vdagent_backend/events.py`, khoảng dòng 64-67.
- Hiện tại: hàm tồn tại nhưng không có nơi nào gọi — di sản từ thiết kế health-broadcast trước khi
  `2026-09-26-agent-plugins-design.md` bỏ health (agent luôn available, không còn trạng thái
  health).
- Việc cần làm: xác nhận lại bằng `grep -rn "\.broadcast(" backend/` rằng thật sự không còn nơi
  nào gọi, rồi xoá hàm. Nếu có test riêng cho nó, xoá test tương ứng.
- Ưu tiên: thấp, làm cùng lúc với T1 (cùng file khu vực, có thể gộp 1 commit `refactor(backend):
  ...`).

## insight

### T3 — Thêm test cho nhánh validate `send_to_agent` thiếu/rỗng tham số `agent`

- File: `agents/insight/vdagent_insight/bridge.py`, khoảng dòng 78-79 (`awrap_tool_call`, nhánh
  "requires 'agent'").
- Hiện tại: chỉ có test cho nhánh thiếu `message`
  (`tests/test_agent.py`, case `("e5", "send_to_agent", {"agent": "data"})`). Nhánh thiếu/rỗng
  `agent` (ví dụ `{"message": "..."}` hoặc `{"agent": "", "message": "..."}`) chưa có test, dù code
  đã xử lý.
- Việc cần làm: thêm 1 case tương tự case `e5` hiện có nhưng đảo lại — thiếu/rỗng `agent`, còn
  `message` hợp lệ — assert ra đúng thông báo lỗi tương ứng trong `bridge.py:78-79`.
- Ưu tiên: thấp, rủi ro code gần như bằng 0 (nhánh code đã đúng, chỉ thiếu bằng chứng test).

## report

### T4 — Test đường "gọi tool sau khi revise"

- File: `agents/report/vdagent_report/graph.py` (graph: `revise → agent → tools → agent ...`).
- Hiện tại: graph hỗ trợ cấu trúc này nhưng không có test nào lái kịch bản model gọi thêm tool ở
  lượt thử lại thứ 2 (sau khi bị judge từ chối) thay vì trả draft mới ngay.
- Việc cần làm: viết 1 test kịch bản LLM 2 bước sau revise: bước đầu bị reject bởi Jev
  (`Verdict.acceptable` thấp), bước revise xong model gọi thêm 1 tool call trước khi ra draft cuối
  — xác nhận `ctx` nhận đúng chuỗi assistant/tool/assistant events và chỉ 1 câu trả lời cuối được
  emit.

### T5 — Test cấu trúc graph (node/edge) độc lập với hành vi

- File: `agents/report/vdagent_report/graph.py`, hàm build graph (khoảng dòng 83-96).
- Hiện tại: coverage hoàn toàn qua behavior test (`invoke()`), không có assertion trực tiếp lên
  danh sách node/edge — một lỗi nối dây (wiring typo) sẽ chỉ lộ ra gián tiếp qua test hành vi.
- Việc cần làm: thêm 1 test nhỏ kiểm tra `graph.nodes` / cạnh nối đúng như spec's mermaid diagram
  (`agent-freedom-design.md` dòng 180-188): `agent→tools`, `tools→agent`, `agent→assess`,
  `assess→revise|finalize`, `revise→agent`, `finalize→END`.

### T6 — Test guard `recursion_limit` thật sự trigger

- File: `agents/report/vdagent_report/agent.py`, dòng ~126 (`recursion_limit = 3*max_steps+10`).
- Hiện tại: không có test nào dùng scripted model "không bao giờ dừng" để xác nhận guard này thực
  sự chặn vòng lặp vô hạn thay vì treo test suite.
- Việc cần làm: viết test với `ScriptedLLM` luôn trả tool-call giả (không bao giờ ra draft cuối),
  assert graph dừng lại ở giới hạn recursion thay vì chạy mãi (dùng `pytest.raises` cho exception
  LangGraph ném ra khi chạm `recursion_limit`, hoặc xác nhận hành vi fallback nếu code có catch nó
  — đọc code trước khi viết assertion, vì hiện chưa rõ nó propagate hay được nuốt).
- Ưu tiên: trung bình — đây là bảo vệ chống treo, đáng có test dù rủi ro thấp trong thực tế.

### T7 — (tuỳ chọn, ưu tiên thấp) Test dedup artifact id trùng giữa 2 tool result trong cùng 1 bước

- File: `agents/report/vdagent_report/graph.py`, dòng ~130 (`list(dict.fromkeys(found))`).
- Việc cần làm: thêm test 2 tool result cùng chứa 1 artifact id (`ds_/ch_/rp_`) trong cùng 1 bước,
  xác nhận id chỉ xuất hiện 1 lần trong danh sách artifact được track.
- Ưu tiên: thấp, có thể bỏ qua nếu thời gian hạn chế.

## Mục cần quyết định trước khi làm (không tự ý code)

### D1 — Có nên gộp ~350 dòng test scaffolding trùng lặp giữa orchestrator/data/compare?

- 3 agent này có `tests/test_agent.py` gần như byte-giống nhau (chỉ khác import). Đây là **chủ
  đích thiết kế** ("mỗi agent tự chứa, copy chứ không import" — P5/T11 trong
  `agent-template-design.md`/`agent-plugins-design.md`), không phải nợ kỹ thuật ngoài ý muốn.
- Nếu muốn gộp thành 1 package test-support dùng chung, đó là một **thay đổi kiến trúc mới**, cần
  quyết định + có thể cần sửa spec (`docs/superpowers/specs`) trước, không nằm trong phạm vi
  "refactor theo docs hiện có" của phiên này.
- **Quyết định:** để nguyên, không làm trong phiên này, trừ khi có quyết định khác.

### D2 — docs/agent-a/*, CLAUDE.local.md, .personal/* lỗi thời

- Không nằm trong phạm vi code, nhưng đáng được note lại: các tài liệu này mô tả kiến trúc
  TypeScript/PostgreSQL không khớp code Python hiện tại. Chủ dự án đã quyết định bỏ qua khi lập
  plan này (2026-09-29), nhưng chưa quyết định có nên archive/đánh dấu "stale" chính thức hay
  không.
- **Không tự ý sửa/xoá các file này.** Nếu chủ dự án muốn dọn, mở task riêng ngoài phạm vi refactor
  code này.
