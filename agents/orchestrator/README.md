# Orchestrator Agent — bản cơ bản

Plugin Python chạy trong Backend, nhận câu hỏi về **một căn**, lập kế hoạch, gọi specialist qua
`send_to_agent` và trả lời bằng số liệu từ artifact. Code nằm trong `vdagent_orchestrator/`;
test nằm trong `vdagent_orchestrator/tests/`. Không có service Orchestrator riêng.

## Phạm vi và contract

| Yêu cầu | Các agent được gọi |
|---|---|
| Vì sao căn A12-08 bán chậm? | Data → Insight |
| So sánh căn A12-08 với các căn tương đồng | Data → Compare |
| Cho tôi biểu đồ căn A12-08 | Data → [Insight ∥ Compare] → Chart |
| Xuất báo cáo căn A12-08 | Data → [Insight ∥ Compare] → Chart → Report |

Nếu người dùng chỉ định một loại phân tích kèm biểu đồ/báo cáo, chỉ dùng loại phân tích đó.
Mỗi câu hỏi phải có mã căn và đủ nghĩa; câu hỏi nhiều căn không được tự chọn một căn.

Contract chạy thật là `StepSpec@1` / `AgentReport@1` trong `contracts/vdagent_contracts/` và SDK
`InvocationContext` trong `sdk/vdagent_sdk/`. `docs/archive/agent-contracts-legacy/contract-v1.0.md` đã được
đánh dấu là giao thức cũ. Các mô tả cũ về `llm1.py`, `dispatcher.py`, `replan.py`, decision card
và ngân sách 9 LLM calls không phải implementation này.

## Một lượt chạy

| File | Trách nhiệm |
|---|---|
| `agent.py` | Chọn structured request, deterministic planner, LLM planner hoặc legacy debug loop |
| `planner.py` | Phân loại từ khóa và biên dịch yêu cầu thành specs/dependencies |
| `llm_planner.py` | LLM đề xuất intent/plan; code kiểm tra trước khi dispatch |
| `dag.py` | Kiểm tra catalog, ID, dependency, cycle và chia wave |
| `executor.py` | Gọi agent, kiểm tra kết quả, chuyển ref và lưu `run_state@1` |
| `answer.py` | Trích số liệu và limitation từ kết quả, ghi outcome lên Backend |
| `settings.py`, `llm.py`, `mcp_client.py` | Cấu hình và client |

LLM chỉ đề xuất intent/agent/operation/dependency; code tạo specs, scope, input refs và pins.
Prompt của đường này là `llm_planner.system_prompt()`; `prompts/system.md` phục vụ legacy loop.
`STEP_OPERATIONS` trong `planner.py` khai báo operation mà workflow một căn biên dịch được.
Data có `aggregate_metrics` trong catalog nhưng workflow này chưa hỗ trợ operation đó.

Plan chỉ được dùng các agent cần cho intent. Chart phụ thuộc tất cả analysis đã chọn; Report
phụ thuộc các analysis và Chart. Plan sai bị từ chối trước khi gọi worker, không tự fallback.
Mỗi wave phát `send_to_agent` calls rồi gọi `call_agent` và `emit_tool_result` theo SDK. Insight và
Compare chạy song song; wave sau chờ wave trước giải quyết. Data lỗi thì dừng downstream.
Chart/Report có thể dùng kết quả còn lại khi một nhánh lỗi, kèm limitation và outcome `partial`.

Executor kiểm tra report đúng run/step/idempotency key/snapshot/semantic; artifact phải đúng type,
hash, snapshot/semantic và trạng thái `VALID` hoặc `PARTIAL`. Giữ limitation và partial của artifact
kể cả khi worker không chép vào report. Scope thực tế do Backend xác định.

`run_state` lưu plan, waves, trạng thái từng bước và refs trước khi chạy, sau mỗi wave và khi kết
thúc/timeout. Chạy lại cùng plan trong cùng run có thể dùng lại bước completed. Chưa tự resume sau
Backend restart; Backend đánh dấu công việc đang dở là interrupted.

## Cấu hình và chạy

Cần Python 3.12 và uv. Từ repo root: `uv sync --frozen`.
Biến môi trường hoặc `agents/orchestrator/.env` (file thắng process env; không commit `.env`):

| Biến | Ý nghĩa |
|---|---|
| `ORCH_LLM=off` | Không cần key; dùng mã căn và từ khóa tiếng Việt để lập plan |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL` | Bắt buộc khi LLM bật |
| `LLM_TIMEOUT_S` | Timeout mỗi lần gọi LLM, mặc định 120 giây |
| `ORCH_SNAPSHOT_ID` | Snapshot rõ ràng cho free text; Data chỉ nhận snapshot APPROVED |
| `ORCH_SEMANTIC_VERSION` | Phiên bản semantic tương ứng snapshot |
| `ORCH_DAG_TIMEOUT_S` | Timeout vòng thực thi DAG, mặc định 300 giây; không gồm lập plan/tạo câu trả lời |
| `ORCH_LEGACY_LOOP=on` | Debug vòng tool cũ khi có LLM; không dùng để kiểm chứng DAG |

Chạy toàn stack không cần key: `make mock-up` (kho giả) theo README ở repo root, mở
`http://localhost:8001`, chọn Alice và Orchestrator. Offline Compose đặt pin demo
`SNAP-2026-09-28` / `sc-1`. Live demo: `make up` sau khi điền `.env` (README "Quick Start").

Đầu vào structured cũng được hỗ trợ; pin lấy trực tiếp từ request:

```json
{
  "contract": "AnalysisRequest@1",
  "question": "Vì sao căn A12-08 bán chậm? So sánh, vẽ biểu đồ và xuất báo cáo.",
  "subject_unit_code": "A12-08",
  "wants": ["explain", "compare", "chart", "report"],
  "snapshot_id": "SNAP-2026-09-28",
  "semantic_config_version": "sc-1"
}
```

## Kế hoạch bản cơ bản và kiểm thử

1. Chạy test hiện có, bổ sung test thất bại cho compiler/contract.
2. Sửa trong module hiện có: operation, dependency, request type, report identity và trạng thái artifact.
3. Kiểm tra unit và golden case với engine, MCP handlers, store và năm worker thật.
4. Chạy regression workspace; cập nhật cấu hình mẫu và hướng dẫn.

Khả thi vì pipeline/contracts đã có. Đánh đổi: giữ luồng một câu hỏi đầy đủ để kiểm chứng end-to-end;
không đổi API Backend, catalog worker, dependency hoặc build/test configuration. Phát triển theo TDD.

```powershell
uv run pytest -q -p no:cacheprovider agents/orchestrator
uv run pytest -q -p no:cacheprovider
```

`test_llm_planner.py`: schema, operation, dependency, đầu ra và mã căn.
`test_dag.py`: wave, partial failure, timeout, ref/report validation, reuse và B5 Report.
`test_ws5_golden.py`: engine thật, toàn chuỗi worker, lineage, báo cáo và scope.
`test_agent.py`: plugin setup và legacy SDK/tool loop.

Kiểm chứng ngày 2026-10-01 trên Python 3.12:

- TDD: 19 test mới thất bại trước sửa; sau sửa 111 test Orchestrator pass. Bổ sung một golden case
  với LLM giả lập và worker thật, cũng pass trong regression workspace.
- Regression workspace: 1.341 pass, 29 skip, 14 subtest pass; 4 test script Docker lỗi vì Windows
  chọn WSL không có `/bin/bash`. Chạy lại toàn bộ `backend/tests/test_docker_setup.py` với Git Bash
  trên PATH: 7/7 pass. Không sửa build/test configuration. Có warning Alembic về index `ux_user_scopes`.
- Backend offline thật trên localhost: bốn câu hỏi trong bảng phạm vi đều hoàn thành qua REST/MCP;
  báo cáo có 6 phần, 5/5 chart API đọc được, evidence validation pass. Outcome `partial` giữ các
  limitation nghiệp vụ. Dữ liệu kiểm tra nằm riêng trong `var/orchestrator-smoke-20261001/` (gitignored).
- Chưa kiểm tra provider LLM live hoặc render trình duyệt trong lần thay đổi này.

## Giới hạn

- Chưa có context cho câu hỏi nối tiếp, replan/retry tự động hoặc provider dự phòng.
- Chưa có luồng hỏi–đáp tiếp tục step khi worker trả `input_required`.
- Chưa áp deadline riêng cho từng worker; `deadline_s` trong StepSpec lấy từ catalog.
- Chưa hỗ trợ aggregate, nhiều căn hoặc nhiều snapshot qua planner.
- B-11, B-2, D2b, B-3, B-12 còn chờ nghiệp vụ; giữ limitation, không tự đặt luật.
- Auth production và kiểm chứng LLM live là công việc riêng; test offline không chứng minh hai phần đó.
