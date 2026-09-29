# Data Agent — đặc tả triển khai (AGENT_A)

Tài liệu này chuyển bản **"Thiết kế sơ bộ Data Agent v01"** (Minh, 24/09/2026; sẽ đặt tại
`docs/agent-a/data/design.md`) thành việc cụ thể
trong repository: code nằm ở đâu, contract nào phải giữ, chia task ra sao và mỗi gate cần đạt gì.
Bản thiết kế trả lời câu hỏi *làm gì và vì sao*. Tài liệu này trả lời câu hỏi *làm thế nào trong
repo này, theo thứ tự nào*.

- Owner: team AGENT_A. Lead duyệt mọi thay đổi ở mục 3 (contract).
- Nhánh: `feature/data_agent` (code agent), `feature/data_test` (fixture, golden set, eval).
  Merge vào `AGENT_A` qua PR, sau đó lead đưa lên `develop`.
- Trạng thái: **Draft — chờ chốt Gate G0**.

## 1. Hiện trạng và đích đến

| Khía cạnh | Hiện tại trong repo | Đích (thiết kế v01) |
| --- | --- | --- |
| Đầu vào | `{ prompt: string }` qua `agents.delegate` (`message` ≤ 4000 ký tự) | `StepSpec` có cấu trúc + câu hỏi gốc |
| Cách chạy | Pi tự gọi tool (tối đa 4 lượt); preflight bảng trong `analytics.ts` | Pipeline cố định S0→S7, LLM chỉ ở S1–S3 |
| Truy vấn | `warehouse.run_query`: một bảng, chọn cột, `limit`. Không có SQL/filter/join | T1 semantic compiler, T2 template, T3 Text-to-SQL có rào chắn |
| Warehouse | Mock 2 bảng (`monthly_sales`, `customers`) | Schema v2, 12 bảng, có snapshot |
| Đầu ra | Chuỗi văn bản + `ds_xxxxxxxxxxxx` trong `web_datasets` (rows jsonb) | Data Package: dataset(s) + manifest + DQ report + limitations |
| Lỗi | Chuỗi bắt đầu `error:` | 8 mã lỗi (mục 3.4) |
| Kiểm chứng | Không có | SQL guard, grain, đối soát, DQ, kiểm số trong tóm tắt |

**Nguyên tắc chuyển đổi:** mỗi gate phải merge được độc lập và **không làm vỡ luồng hiện tại**.
Nhánh prompt cũ `{ prompt }` vẫn chạy song song cho tới Gate G4.

## 2. Vị trí code

```text
src/agents/data/
├── index.ts                 # Plugin: descriptor + run(). Chọn StepSpec pipeline hoặc nhánh prompt cũ
├── contract.ts              # TypeBox: StepSpec, Envelope, Manifest, ErrorCode. Nguồn sự thật duy nhất
├── pipeline/
│   ├── state.ts             # StepState dùng chung S0–S7, budget, trace span
│   ├── s0-intake.ts         # validate, idempotency, khóa snapshot
│   ├── s1-resolve.ts        # thực thể → ID, từ nghiệp vụ → catalog, phát hiện mơ hồ
│   ├── s2-plan.ts           # data_plan + chọn tầng T1/T2/T3
│   ├── s3-generate.ts       # gọi query/*
│   ├── s4-static-check.ts   # sql guard
│   ├── s5-execute.ts        # thực thi, sửa lỗi tối đa 2 vòng
│   ├── s6-verify.ts         # grain, đối soát, DQ, metric
│   └── s7-materialize.ts    # lưu dataset + manifest, soạn envelope
├── semantic/
│   ├── layer.ts             # entities, dimensions, metrics, filters, JOIN graph + semantic_version
│   └── catalog.ts           # sinh catalog rút gọn cho Orchestrator từ layer.ts
└── query/
    ├── compile.ts           # T1: plan → SQL + lineage (tất định)
    ├── templates.ts         # T2: template đã duyệt
    └── text2sql.ts          # T3 (Gate G6)

test/agent-a-data-*.test.ts          # unit test offline
test/fixtures/agent-a/                # schema v2 thu nhỏ, value index, golden tasks
```

Quy ước:

- Semantic layer viết bằng **TypeScript có type**, không dùng YAML. Thêm dependency parser YAML
  cần platform duyệt, và TS cho kiểm tra kiểu miễn phí. Ví dụ YAML trong bản thiết kế chỉ để minh họa.
- `contract.ts` là file **duy nhất** định nghĩa contract. Orchestrator và Report import từ đây,
  không tự khai báo lại kiểu.
- Không dùng `createAnalyticsAgent` cho nhánh pipeline mới. Nhánh prompt cũ vẫn gọi logic hiện có
  cho tới G4.

## 3. Contract (chốt ở Gate G0)

Mọi thay đổi ở mục này cần lead duyệt và tăng `contract_version` theo SemVer. Thêm trường tùy
chọn thì tăng minor. Đổi nghĩa hoặc xóa trường thì tăng major.

### 3.1. Truyền StepSpec qua kênh hiện có

`agents.delegate` thuộc CORE và chỉ nhận `message: string`. Để **không phải sửa tool của CORE**
ở giai đoạn đầu:

- Orchestrator gửi `message` = `"STEP_SPEC " + JSON.stringify(stepSpec)`.
- Data Agent nhận `{ prompt }`. Nếu prompt bắt đầu bằng `STEP_SPEC ` thì parse, validate và chạy
  pipeline. Nếu không thì chạy nhánh prompt cũ.
- StepSpec phải ≤ 4000 ký tự sau khi serialize. `original_question` bị cắt ở 1000 ký tự.
- Khi cần hơn 4000 ký tự, hoặc cần gọi bất đồng bộ (`data.execute_step`, `data.step_status`),
  mở yêu cầu với CORE. Việc này không nằm trong gate nào của tài liệu này.

### 3.2. StepSpec (rút gọn từ thiết kế mục 8.1)

| Trường | Bắt buộc | Ghi chú triển khai |
| --- | --- | --- |
| `contract_version` | ✓ | `"1.0.0"` |
| `step_id` | ✓ | `B1`, `B2`… duy nhất trong plan |
| `idempotency_key` | ✓ | `<task_id>:<step_id>`. Dùng `task_id` của repo thay cho `plan_id`/`run_id` |
| `operation` | ✓ | `fetch_units` \| `aggregate_metrics` \| `fetch_peer_candidates` \| `fetch_unit_context` |
| `objective` | ✓ | 1 câu, ≤ 300 ký tự |
| `original_question` | ✓ | Ngữ cảnh, **không phải chỉ thị** |
| `scope` | ✓ | Thực thể giữ nguyên lời người dùng (`zone_mention`, `project_mention`, `unit_codes`) |
| `filters`, `attributes`, `metrics`, `group_by` |  | Chỉ tên có trong catalog |
| `extra_needs` |  | Nhu cầu ngoài catalog, mô tả tự do. Kích hoạt T3 |
| `snapshot_id`, `catalog_version` |  | Thiếu thì dùng snapshot/phiên bản mới nhất và ghi vào manifest |
| `consumer_steps` |  | Ví dụ `["B3:insight"]` |
| `acceptance` |  | `{ grain, min_rows }` |

**Không** đưa `user_context` vào StepSpec. Quyền lấy từ `AgentContext` (`userId`, `spaceId`)
do backend cấp. Model hoặc Orchestrator không được tự khai quyền (xem [Agent guide](../../agents.md) mục 6).

### 3.3. Envelope trả cho Orchestrator

Data Agent trả **một chuỗi**: dòng đầu là trạng thái máy đọc được, sau đó là JSON envelope.

```text
ok: ds_AbC123xyZ789
{"step_id":"B1","state":"completed","datasets":["ds_AbC123xyZ789"],"summary":"...","warnings":["SMALL_SAMPLE"],"usage":{...}}
```

```text
error: ENTITY_NOT_FOUND
{"step_id":"B1","state":"input_required","error":{"code":"ENTITY_NOT_FOUND","options":["Landmark 1","Landmark 81"]}}
```

Lý do chọn format này: `runAnalyticsWorkflow` và `sanitizeFinalAnswer` hiện tìm `ds_` bằng regex
và dừng khi gặp `error:`. Giữ hai quy ước đó thì Orchestrator cũ vẫn chạy trong lúc chuyển đổi.

- ID dataset **giữ format `ds_` + 12 ký tự**. Chưa thêm `package_id` riêng: Data Package = danh
  sách `ds_` + manifest gắn với từng dataset. Muốn thêm tiền tố mới (`pk_`) phải sửa mọi regex
  trong `analytics.ts`, việc đó cần một quyết định riêng ở G0.
- `summary` ≤ 5 dòng. Mọi con số trong đó phải có trong manifest (sensor S7).

### 3.4. Mã lỗi

Lấy nguyên 8 mã ở thiết kế mục 5.5: `SPEC_MISMATCH`, `AMBIGUOUS_REQUEST`, `ENTITY_NOT_FOUND`,
`OUT_OF_SCOPE`, `DATA_UNAVAILABLE`, `DQ_BLOCKING`, `LOW_CONFIDENCE`, `BUDGET_EXCEEDED`.

- `LOW_CONFIDENCE` là **cảnh báo**: trạng thái `ok:` và nằm trong `warnings`. 7 mã còn lại trả
  `error: <CODE>`.
- Hủy (`context.signal.aborted`) thì `throw` lại, không trả mã lỗi.

### 3.5. Manifest

Theo thiết kế mục 8.2, bổ sung các trường mà repo cần:

- `dataset_id`, `task_id`, `step_id`, `grain`, `rows`, `columns[]` (tên, kiểu, ngữ nghĩa),
  `filters[]`, `sql`, `sql_hash`, `tier` (`T1`|`T2`|`T3`|`legacy`), `snapshot_id`,
  `semantic_version`, `dq[]`, `limitations[]`.
- Lưu ở đâu: cột `manifest jsonb` mới trên `web_datasets` hoặc bảng riêng. **Cần migration**,
  thuộc vùng Data persistence. Mở yêu cầu ở G0, triển khai ở G4.

## 4. Phụ thuộc ngoài team

| Cần | Owner | Chặn gate | Phương án tạm |
| --- | --- | --- | --- |
| Warehouse provider chạy được SQL (read-only, timeout, giới hạn dòng) trên schema v2 | DATA | G2 (thực thi) | Unit test chỉ kiểm SQL biên dịch + lineage. Integration test chạy trên PostgreSQL test (`TEST_DATABASE_URL`) seed schema v2 thu nhỏ |
| Engine DW cho POC (DuckDB / PostgreSQL) → dialect SQL | DATA + lead | G2 | Viết compiler cho dialect PostgreSQL trước |
| Migration lưu manifest | Data persistence | G4 | Không tạm lưu vào cột `columns`; G1–G3 trả manifest trong envelope, chờ migration để lưu |
| Tăng giới hạn `message` / endpoint bất đồng bộ | CORE | Sau G6 | Tiền tố `STEP_SPEC` + ≤ 4000 ký tự |
| Dependency parser SQL cho sql guard | Platform (`package.json`) | G3 | Guard dựa trên AST của chính compiler (T1/T2 không cần parse) |
| Chọn model theo bước (S1 nhỏ, T3 mạnh) | Runtime | G6 | Dùng `PI_DEFAULT_MODEL` |

## 5. Gate và task

Mỗi gate là một mốc merge vào `AGENT_A`. Gate chỉ được coi là đạt khi **mọi tiêu chí thoát** đúng
và lead approve PR. Mã task: `D-` do thành viên data_agent làm, `DT-` do thành viên data_test làm,
`O-` do thành viên orchestrator làm.

### G0 — Chốt contract (không đổi hành vi)

| Task | Nội dung | Nhánh |
| --- | --- | --- |
| D-01 | `contract.ts`: TypeBox cho StepSpec, Envelope, Manifest, ErrorCode + hàm `parseStepSpec`, `formatEnvelope` | data_agent |
| D-02 | Test: ví dụ hợp lệ/không hợp lệ cho mỗi schema; envelope luôn có dòng đầu `ok: ds_…` hoặc `error: CODE` | data_agent |
| DT-01 | Fixture schema v2 thu nhỏ (các bảng cho 4 operation, ~50 căn, 2 phân khu, 1 snapshot) + mô tả đáp án | data_test |
| L-01 | Chốt 5 quyết định ở mục 7 và ghi kết quả vào tài liệu này | lead |

Tiêu chí thoát: contract merged; Orchestrator (O-) đã review và import được kiểu; mục 7 không còn
câu hỏi chặn G1–G2; mọi test cũ vẫn xanh.

### G1 — Walking skeleton

| Task | Nội dung | Nhánh |
| --- | --- | --- |
| D-10 | `index.ts` nhận tiền tố `STEP_SPEC`, chạy S0 (validate, idempotency theo `idempotency_key` trong task, trả `OUT_OF_SCOPE` nếu operation lạ). Tạm dùng `run_query` hiện có cho S5, rồi đóng gói envelope | data_agent |
| D-11 | `pipeline/state.ts` + budget (số lượt LLM/SQL, thời gian) + trace span ghi qua `context.publish` | data_agent |
| O-10 | Orchestrator gửi StepSpec cho bước dữ liệu **sau cờ** `DATA_STEP_SPEC=1`; mặc định vẫn gửi prompt | orchestrator |
| DT-10 | Test hai chiều: prompt cũ → hành vi như trước; StepSpec → envelope đúng format | data_test |

Tiêu chí thoát: bật cờ và chạy luồng `data → compare → report` end-to-end trên mock mà không vỡ;
tắt cờ thì không khác gì bản hiện tại.

### G2 — Semantic layer + T1 cho `fetch_units`, `aggregate_metrics`

| Task | Nội dung | Nhánh |
| --- | --- | --- |
| D-20 | `semantic/layer.ts` cho các bảng trong fixture: entity, dimension (có synonym tiếng Việt, không dấu), metric (tử/mẫu số, `min_n`, `formula_id`), filter (`slow_moving` đọc ngưỡng từ config), JOIN graph | data_agent |
| D-21 | `semantic/catalog.ts`: catalog rút gọn ≤ ~1.500 token, gắn `semantic_version` | data_agent |
| D-22 | S1 phân giải thực thể bằng value index (khớp chính xác → không dấu → gần đúng, ≤ 3 gợi ý) | data_agent |
| D-23 | S2 + `query/compile.ts`: plan → SQL + lineage, tất định; **luôn tự chèn** filter snapshot và scope | data_agent |
| DT-20 | Golden set v0: 20 task T1 (KPI + fetch_units), đáp án duyệt 2 lần | data_test |
| DT-21 | Test: snapshot SQL biên dịch cho từng golden task; paraphrase (không dấu, viết tắt) ra cùng plan | data_test |

Tiêu chí thoát: 100% golden T1 ra đúng SQL/plan (offline); integration test trên PostgreSQL test
khớp đáp án ≥ 98%; không có ngưỡng nghiệp vụ gõ cứng trong code (có test chặn).

### G3 — Kiểm chứng (S4–S6)

| Task | Nội dung | Nhánh |
| --- | --- | --- |
| D-30 | S4: SELECT-only, whitelist bảng/cột, cạnh JOIN phải có trong graph. Lỗi kèm `fix` như thiết kế mục 7.1 | data_agent |
| D-31 | S5: thực thi read-only + timeout + giới hạn dòng; lỗi thì quay lại S3 tối đa 2 vòng | data_agent |
| D-32 | S6: grain duy nhất, số dòng trong khoảng, đối soát tổng, DQ rule, metric có n và cờ `SMALL_SAMPLE` | data_agent |
| DT-30 | Bộ an toàn (E6): SQL ghi, bảng ngoài whitelist, thiếu filter snapshot, prompt injection trong `original_question` | data_test |
| DT-31 | Fixture cấy lỗi (trùng khóa, sold_date sai, giá ròng > giá chào) cho E7 | data_test |

Tiêu chí thoát: **E6 = 0 vi phạm**; E7 recall ≥ 95% trên fixture cấy lỗi; mọi đường S5 lỗi đều có test.

### G4 — Data Package + tích hợp Report

| Task | Nội dung | Nhánh |
| --- | --- | --- |
| D-40 | S7: lưu dataset + manifest (sau khi có migration), loại PII, envelope có summary đã kiểm số | data_agent |
| D-41 | Sensor: mọi con số trong `summary` phải có trong manifest | data_agent |
| O-40 | Orchestrator bỏ cờ, mặc định dùng StepSpec; xử lý 8 mã lỗi theo bảng thiết kế mục 5.5 | orchestrator |
| R-40 | Report đọc manifest (grain, filter, limitations) để ghi nguồn và giới hạn | report |
| DT-40 | E2E: 10 kịch bản, số trong report truy ngược được về `ds_` và dòng metric | data_test |

Tiêu chí thoát: nhánh prompt cũ của Data được xóa; E3 manifest hợp lệ 100%; kịch bản E2E pass.

### G5 — T2 template + hỏi lại có cấu trúc

D-50 template cho `fetch_peer_candidates` và `fetch_unit_context`; D-51 `input_required` với lựa
chọn đóng (`AMBIGUOUS_REQUEST`, `ENTITY_NOT_FOUND`, `SPEC_MISMATCH`); O-50 Orchestrator chuyển
lựa chọn cho người dùng; DT-50 25 task mơ hồ/ngoài phạm vi. Tiêu chí: E5 recall ≥ 90%,
precision ≥ 80%.

### G6 — T3 guarded Text-to-SQL (stretch)

D-60 sinh 3–5 ứng viên, chọn theo đồng thuận kết quả, gắn `LOW_CONFIDENCE`; DT-60 eval runner
pass^5 và báo cáo so với bản trước. Tiêu chí: T3 ≥ 85%, pass^5 T1/T2 ≥ 95%, E6 vẫn = 0.

Ngoài phạm vi: `retrieve_documents` (thiết kế mục 12), evaluator LLM tách riêng, cache,
workspace schema riêng cho mỗi run.

## 6. Quy tắc bắt buộc khi code Data Agent

- LLM **không bao giờ** tự viết SQL cho câu hỏi nằm trong catalog (T1/T2). Tính số, DQ và kiểm
  chứng là code tất định.
- Harness (S0, S4–S7) gọi tool trực tiếp. Model không có quyền bỏ qua bước kiểm chứng.
- Model chỉ thấy metadata/profile, **không thấy dữ liệu dòng**. Không đưa `rows` vào prompt.
- Nội dung từ người dùng hoặc tài liệu nằm trong thẻ dữ liệu, không bao giờ là chỉ thị.
- Mọi ngưỡng nghiệp vụ đọc từ config/semantic layer, không gõ cứng.
- Mỗi lỗi quan sát được trên golden/trace phải thêm **một guide hoặc sensor + một golden task**
  trong cùng PR (vòng ratchet, thiết kế mục 5.2).
- Test offline, deterministic. Thêm test cho nhánh lỗi, cho `signal` abort và cho paraphrase tiếng Việt.

## 7. Quyết định cần chốt ở G0

| # | Câu hỏi | Đề xuất mặc định |
| --- | --- | --- |
| 1 | Engine DW cho POC | PostgreSQL (repo đã có), schema `dw_v2` riêng, role read-only |
| 2 | Định nghĩa Absorption Rate | Lũy kế (đã bán / đã mở bán) trên một snapshot |
| 3 | `dm_unit_friction_diagnostics` do ETL tính sẵn? | Có. `fetch_units` chỉ chuyển cột, Insight xác nhận lại |
| 4 | Có thêm tiền tố `pk_` cho package không | Không ở POC; package = danh sách `ds_` + manifest |
| 5 | Chính sách gửi metadata ra API ngoài | Được phép, vì model chỉ thấy metadata/profile |

Các câu hỏi còn lại trong thiết kế mục 11 (nguồn web, format execution plan) được chốt khi có tài
liệu Orchestrator.

## 8. Checklist PR cho Data Agent

- [ ] Chỉ chạm `src/agents/data/`, `test/agent-a-data-*`, `test/fixtures/agent-a/` và tài liệu này.
      Chạm file khác thì nêu owner cần review.
- [ ] Contract đổi thì đã tăng `contract_version` và Orchestrator/Report đã cập nhật trong cùng PR hoặc PR liền kề.
- [ ] Golden/eval không giảm: E2 không giảm quá 1 điểm %, E6 = 0.
- [ ] Chạy `corepack pnpm lint`, `check`, `test`.
- [ ] Ghi gate/task (`G2 / D-23`) trong tiêu đề hoặc mô tả PR.
