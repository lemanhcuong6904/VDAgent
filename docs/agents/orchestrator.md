# Orchestrator Agent

Orchestrator nhận câu hỏi về **một căn**, lập kế hoạch, chạy DAG bằng code qua các lời gọi agent của Backend và trả
lời bằng số liệu trích từ artifact đã kiểm chứng. Đây là plugin Python trong Backend
(`agents/orchestrator/vdagent_orchestrator/`), không phải service riêng. Cách chạy, biến môi trường và lệnh test:
[`agents/orchestrator/README.md`](../../agents/orchestrator/README.md). Kiến trúc tổng thể:
[system.md](../architecture/system.md); quyết định D5: [decisions.md](../architecture/decisions.md).

Gộp từ `docs/agent-a/orchestrator/{README,design}.md` và viết lại theo code ngày 2026-10-04. Bản "design v4" cũ
(`llm1.py`, `intent.py`, `dispatcher.py`, `replan.py`, decision card, `control/`, ngân sách 9 lần gọi LLM) **không còn
trong code**; bản đó còn trong lịch sử Git (commit `aed2917`). [`contract-v1.0.md`](../archive/agent-contracts-legacy/contract-v1.0.md) (archive) mô tả
giao thức 9 message (`DISPATCH`, `REPORT`, …). Orchestrator **không** dùng giao thức này; chỉ Data có một cửa v1.0
riêng (`agents/data/vdagent_data/wire.py`) để gọi trực tiếp, xem [Data README](../../agents/data/README.md).

## 1. Contract

- Gửi: `StepSpec@1` qua `send_to_agent` (`ctx.call_agent`); nhận: đúng một `AgentReport@1` mỗi bước
  (`contracts/vdagent_contracts/messages.py`, `reports.py`). Chi tiết: [agent-contract.md](../contracts/agent-contract.md).
- Đầu vào có cấu trúc: `AnalysisRequest@1` (`subject_unit_code`, `wants`, `snapshot_id`, `semantic_config_version`);
  contract khác → "Không hoàn thành".
- Operation được phép: catalog đóng băng `contracts/vdagent_contracts/catalogs/<agent>.json`; workflow một căn chỉ
  biên dịch các operation trong `planner.STEP_OPERATIONS` (`aggregate_metrics` của Data chưa dùng).

## 2. Chọn đường lập kế hoạch (`agent.py::OrchestratorAgent.invoke`)

| Đầu vào / cấu hình | Planner | Ghi chú |
|---|---|---|
| `AnalysisRequest@1` | `planner.parse_request` → `build_plan` | pin lấy từ request |
| câu tự do, `ORCH_LLM=on` (production) | `llm_planner.plan_with_llm` | LLM đề xuất, code kiểm tra (mục 3) |
| câu tự do, `ORCH_LLM=off` | `planner.classify` (mã căn + từ khóa tiếng Việt) | không có mã căn → giải thích, không chạy |
| `ORCH_LEGACY_LOOP=on` | vòng tool LiteLLM cũ (`prompts/system.md`) | chỉ để debug, nằm ngoài DAG |

Snapshot và semantic cho câu tự do lấy từ `ORCH_SNAPSHOT_ID` / `ORCH_SEMANTIC_VERSION`; thiếu → `SNAPSHOT_REQUIRED` /
`SEMANTIC_VERSION_REQUIRED`, không bao giờ dùng "latest". Production pin `SNAP-20260630-01` / `3.1.0`; stack giả pin
`SNAP-2026-09-28` / `sc-1`.

**Luật nhu cầu** (`planner.normalize_wants`, dùng chung cho hai planner): biểu đồ/báo cáo mà không nêu loại phân tích
→ cần cả Insight và Compare; báo cáo → cần Chart. Nêu một loại phân tích kèm biểu đồ/báo cáo → chỉ dùng loại đó.

| Câu hỏi (ví dụ) | Kế hoạch |
|---|---|
| Vì sao căn … bán chậm? | Data → Insight |
| So sánh căn … với các căn tương đồng | Data → Compare |
| Cho tôi biểu đồ căn … | Data → [Insight ∥ Compare] → Chart |
| Xuất báo cáo căn … | Data → [Insight ∥ Compare] → Chart → Report |

## 3. LLM planner (`llm_planner.py`, prompt `orch-llm-plan-1.2.0`)

LLM nhận câu hỏi và catalog, không có tool, trả một JSON
`{"intent": {in_scope, subject_unit_code, wants}, "steps": [{step_id, agent, operation, depends_on}]}`. Code quyết
định mọi thứ còn lại:

- schema chặt (`extra=forbid`): LLM không viết được spec, snapshot hay id;
- `dag.validate_plan`: agent/operation có trong catalog, dependency tồn tại, không chu trình, một snapshot/semantic;
- luật vai trò: đúng một bước Data không phụ thuộc; Insight/Compare phụ thuộc Data; Chart dùng mọi phân tích đã
  chọn; Report dùng các phân tích và Chart;
- các bước khớp `wants`, và mã căn phải xuất hiện trong câu hỏi;
- code điền spec (`planner.step_spec`), input binding, chế độ dependency (`chart`, `report`: `any`) và pin.

Vi phạm → `PlanError`, run thất bại an toàn, **không agent nào được gọi**, không fallback sang planner tất định. Output
LLM được chấp nhận lưu trong `run_state.payload.plan.provenance` (planner, model, prompt version, số lần gọi, độ trễ,
plan thô). Ngoài phạm vi (`OUT_OF_SCOPE`) → giải thích, không tạo run.

## 4. Thực thi (`dag.py`, `executor.py`)

- `validate_plan` trả các wave, ví dụ `[[B1], [B2, B3], [B4], [B5]]`. Step id dạng `B<n>`, duy nhất.
- Mỗi wave là một assistant step gồm các lời gọi `send_to_agent`; engine Backend áp các luật của nó (hàng đợi theo
  (user, agent), `max_depth`, wait-for graph). Các lời gọi trong một wave chạy song song (`asyncio.TaskGroup`, B2 ∥ B3);
  wave sau chỉ bắt đầu khi wave trước xong.
- Kiểm tra ở mỗi ranh giới: reply `error: …` → `CALL_REJECTED`; không đúng một `AgentReport@1` của bước → `MALFORMED_REPORT`;
  mỗi ref trả về phải đúng type catalog khai báo, ghim hash, đọc được bằng `artifact_get` theo user, cùng snapshot /
  semantic, trạng thái `VALID`/`PARTIAL` (các mã `REF_*`). Chỉ khi đó ref mới được chuyển xuống bước sau.
- Dependency `all` / `any`: với `any`, nhánh lỗi được báo cho bước sau là `UPSTREAM_FAILED:<agent>`. Data lỗi → dừng
  downstream. Chart/Report vẫn chạy với nhánh còn lại, kèm limitation và outcome `partial`.
- Một deadline cho cả run (`ORCH_DAG_TIMEOUT_S`, mặc định 300 s): hết hạn → hủy lời gọi đang chờ, `run_state` `timed_out`,
  engine trả `DEADLINE_EXCEEDED`. Chưa có deadline riêng từng worker.
- `run_state@1`: một artifact, có version trước khi chạy, sau mỗi wave và khi kết thúc/timeout (plan, trạng thái bước,
  thời điểm, refs, lỗi, limitation). Chạy lại cùng plan trong cùng task dùng lại bước đã xong. Backend restart → task
  `failed / interrupted`, không tự resume.

## 5. Câu trả lời (`answer.py`)

Số liệu chỉ trích từ artifact `insight` / `comparison` của các bước đã hoàn tất, không tính trong Orchestrator; mọi
artifact được dẫn id. Run lỗi bắt đầu bằng "Không hoàn thành" kèm bước và mã lỗi; run partial nêu phần thiếu. Tập peer
được gắn B-11. Outcome ghi lên Backend qua `ctx.report_outcome` (`completed | partial | failed`).

## 6. Giới hạn

- Chưa có ngữ cảnh câu hỏi nối tiếp, replan/retry tự động, provider LLM dự phòng.
- Chưa có vòng hỏi–đáp khi worker trả `input_required`.
- Chưa hỗ trợ aggregate, nhiều căn, nhiều snapshot.
- LLM là phụ thuộc runtime: LLM lỗi → run thất bại (`LLM_PLAN_UNAVAILABLE`).
- Blocker nghiệp vụ B-11, B-2, D2b, B-3, B-12 và F-05 (auth): [decisions.md](../architecture/decisions.md).

## 7. Kiểm thử

`agents/orchestrator/vdagent_orchestrator/tests/`: `test_llm_planner.py` (schema, operation, dependency, grounding),
`test_dag.py` (wave, lỗi một phần, timeout, kiểm tra ref/report, dùng lại bước, B5), `test_ws5_golden.py` (engine thật,
cả chuỗi worker, lineage, scope), `test_agent.py` (plugin setup, legacy loop). Golden E2E:
[e2e-golden.md](../testing/e2e-golden.md).
