# Refactor plan — 2026-09-29

Status: active · Owner: (điền tên khi nhận việc) · Bắt đầu: 2026-09-29

## 0. Vì sao có tài liệu này

Phiên làm việc 2026-09-29 xuất phát từ yêu cầu "copy code từ `vde-agent-demo/agents` sang
`Team_6_cAi/agents` rồi refactor theo docs". Trong lúc thực hiện đã phát hiện:

1. Code trong `vde-agent-demo` implement một kiến trúc **khác hẳn** và **không tương thích** với
   kiến trúc thật của `Team_6_cAi` (thiếu hẳn package `vdagent_contracts`, dùng contract
   StepSpec/Envelope không có tài liệu nào trong repo này mô tả đầy đủ). Bản copy ban đầu đã
   **bị revert** bằng `git checkout` + `git clean` — xem mục 2.
2. Repo có **hai bộ tài liệu thiết kế xung đột nhau**:
   - `docs/superpowers/specs/*.md` — kiến trúc **thật, đã implement**, khớp với code hiện tại
     (`sdk/`, `backend/`, `agents/`). Đây là nguồn sự thật cho refactor này.
   - `docs/agent-a/*.md`, `CLAUDE.local.md`, `.personal/*` — mô tả một kiến trúc **TypeScript +
     PostgreSQL** (`src/agents/*.ts`, `analytics.ts`) chưa từng tồn tại trong repo. Theo quyết định
     của chủ dự án (2026-09-29), bộ tài liệu này **bị coi là lỗi thời và bị bỏ qua** khi lập kế
     hoạch này. Không xoá, không sửa — chỉ không dùng để dẫn dắt refactor.
3. Sau khi revert, đối chiếu sâu (4 agent review, ~30 claim/phần, trích dẫn file:line cụ thể) giữa
   code hiện tại và `docs/superpowers/specs/*.md` cho kết quả: **codebase đã khớp spec gần như
   tuyệt đối**. Không có sai lệch kiến trúc nào cần sửa lớn. Chi tiết: mục 3.

**Kết luận: đây không phải một cuộc refactor lớn.** Việc cần làm là một đợt hardening nhỏ (thêm
test còn thiếu, sửa vài chỗ cosmetic) — xem `TASKS.md`.

## 1. Nguồn sự thật cho refactor này

Đọc theo thứ tự khi cần đối chiếu hành vi:

1. [`docs/superpowers/specs/2026-09-24-vdagent-design.md`](../superpowers/specs/2026-09-24-vdagent-design.md) — kiến trúc tổng, invocation engine, MCP server, DB schema, REST/SSE API.
2. [`docs/superpowers/specs/2026-09-24-agent-template-design.md`](../superpowers/specs/2026-09-24-agent-template-design.md) — khuôn mẫu agent plugin.
3. [`docs/superpowers/specs/2026-09-26-agent-plugins-design.md`](../superpowers/specs/2026-09-26-agent-plugins-design.md) — plugin loader, `InvocationContext`, turn rules R1–R11 (nguồn sự thật hiện hành cho SDK).
4. [`docs/superpowers/specs/2026-09-28-agent-freedom-design.md`](../superpowers/specs/2026-09-28-agent-freedom-design.md) — thiết kế riêng của `insight` (LangChain + memory) và `report` (LangGraph + Jev judge).
5. [`README.md`](../../README.md) — hướng dẫn chạy dự án, đã xác nhận khớp 100% với spec (mục 4 dưới đây).
6. [`sdk/vdagent_sdk/__init__.py`](../../sdk/vdagent_sdk/__init__.py) — interface plugin thật sự, đã xác nhận khớp spec.

**Không dùng** `docs/agent-a/*`, `CLAUDE.local.md`, `.personal/*` để quyết định hành vi code trong
phiên refactor này (lý do: mục 0.2).

## 2. Việc đã làm trong phiên trước khi lập plan

- [x] Copy `vde-agent-demo/agents` → `Team_6_cAi/agents` (ghi đè toàn bộ).
- [x] Phát hiện code copy không tương thích (thiếu `vdagent_contracts`, không khớp doc nào).
- [x] **Revert toàn bộ**: `git checkout -- agents/data agents/insight agents/orchestrator` +
      `git clean -fd` cho các thư mục đó và `agents/_shared`. Xác nhận `git status --porcelain --
      agents` sạch (khớp commit gốc).
- [x] Đối chiếu sâu 4 mảng (agent song song, mỗi agent đọc toàn bộ doc liên quan + toàn bộ code
      liên quan, trích dẫn file:line cho từng claim):
  - `backend/` + `sdk/` — PASS, không có gap chức năng.
  - `orchestrator` + `data` + `compare` (nhóm ReAct-loop giống hệt nhau theo thiết kế) — PASS,
    không có gap.
  - `insight` (LangChain + memory) — PASS, 1 gap nhỏ (thiếu test).
  - `report` (LangGraph + Jev judge) — PASS, vài gap nhỏ (thiếu test edge case).

## 3. Tóm tắt kết quả đối chiếu (bằng chứng chi tiết nằm trong lịch sử agent report của phiên
   2026-09-29, chưa được chép lại đầy đủ vào đây — xem `TASKS.md` cho danh sách hành động)

| Vùng | Kết quả | Gap thật tìm được |
| --- | --- | --- |
| `sdk/vdagent_sdk` | PASS toàn bộ (Agent/InvocationContext/PluginAPI/Memory/turn rules R1-R11) | Không |
| `backend/` (engine, MCP server, DB schema, REST/SSE, config) | PASS toàn bộ (20+ claim cụ thể đối chiếu, kể cả timeout/limit/permission matrix) | 2 cosmetic (T1, T2 trong TASKS.md) |
| `orchestrator`, `data`, `compare` | PASS toàn bộ, 3 agent gần như byte-giống nhau đúng như spec dự định | Không (chỉ có ghi chú về trùng lặp test scaffolding — không bắt buộc sửa) |
| `insight` | PASS gần như toàn bộ (LangChain create_agent, memory recall/save/dedup, bridge sang `ctx`) | 1 test thiếu (T3) |
| `report` | PASS gần như toàn bộ (LangGraph StateGraph, Jev judge, hành vi "judge lỗi = pass" là **chủ đích của spec**, không phải bug) | 3-4 test thiếu (T4-T7) |

Lưu ý quan trọng: một báo cáo validate ở vòng đầu (khi còn dùng docs/agent-a làm chuẩn) từng nghi
ngờ hành vi "Jev lỗi/timeout thì coi như pass" là bug che giấu lỗi. Sau khi đối chiếu lại với spec
thật (`agent-freedom-design.md` dòng 219-220), đây là **hành vi được đặc tả rõ ràng, có chủ đích**
("An HTTP error, timeout (10s) or a missing/malformed answer counts as a pass"). Không sửa.

## 4. Setup / chạy dự án

Repo đã có hướng dẫn setup đầy đủ và đã được xác nhận khớp code trong `README.md` (mục
"Prerequisites", "Plugins", "Environment variables", "Makefile usage", "Docker", "Tests"). Tóm tắt
nhanh cho phiên refactor này:

```sh
# 1. Cài dependency Python (uv workspace) — lần đầu
uv sync

# 2. Tạo .env cho từng agent plugin (lần đầu)
for a in orchestrator data compare insight report; do
  cp -n agents/$a/.env.example agents/$a/.env
done
# rồi điền OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL vào từng agents/<name>/.env
# (insight cần thêm EMBED_MODEL nếu không dùng default; report cần JUDGE_MODEL/JEV_DECISIONS_URL nếu không dùng default)

# 3. Seed dữ liệu demo (SQLite)
make reset-db

# 4. Chạy backend (API + SSE + MCP + serve UI đã build nếu có)
make backend                       # http://localhost:8000
#   HOST=0.0.0.0 make backend      # nếu cần expose ra máy khác

# 5. Chạy frontend dev (terminal khác)
cd frontend && npm install && npm run dev   # http://localhost:5173

# 6. Test
uv run pytest                      # backend + toàn bộ agent plugin
uv run pytest agents/data          # 1 plugin cụ thể
cd frontend && npm test            # frontend
```

Docker (không cần cài Python/Node cục bộ):

```sh
docker compose up --build          # cần agents/<name>/.env cho cả 5 agent trước khi chạy
```

**Việc cần làm trong phiên này (mục Setup):** chạy thử `uv sync` + `uv run pytest` để xác nhận môi
trường sạch thật sự pass trước khi bắt đầu sửa (T0 trong `TASKS.md`) — README mô tả đúng nhưng
chưa ai chạy thực tế xác nhận trong phiên này.

## 5. Nguyên tắc khi thực hiện task

- Mỗi task trong `TASKS.md` là một commit riêng, tự pass test (`uv run pytest agents/<name>` hoặc
  `uv run pytest backend`), theo đúng thói quen atomic-commit đã thấy trong `.personal/CONTRIBUTION.md`
  (test → fix/feat → refactor → docs).
- Không đổi hành vi mà spec không yêu cầu. Đây là hardening theo spec đã có, không phải cơ hội để
  thêm tính năng mới.
- Nếu trong lúc làm phát hiện thêm mâu thuẫn code/doc, dừng lại và hỏi trước khi code (theo yêu cầu
  gốc của chủ dự án), ghi vào mục "Câu hỏi mở" trong `HANDOFF.md`.
- Cập nhật `TASKS.md` (đánh dấu xong) và `HANDOFF.md` (nhật ký) cuối mỗi phiên làm việc trên plan
  này.
