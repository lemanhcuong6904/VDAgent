# Report Agent

Report trình bày kết quả đã có của các agent khác thành báo cáo có thể kiểm chứng. Nó không chạy truy vấn hay phân
tích mới, không gọi agent khác để lấp chỗ trống và không biến tương quan thành kết luận nhân quả. Code:
`agents/report/vdagent_report/`. Hợp đồng chung: [data-contract.md §9](../contracts/data-contract.md#9-ws6-report1-implemented-verified-offline)
(`report@1`), [agent-contract.md](../contracts/agent-contract.md), catalog `contracts/vdagent_contracts/catalogs/report.json`.

Gộp từ `docs/agent-a/report/{README,design,spec}.md` (2026-09-30), đối chiếu lại với code ngày 2026-10-04.
[`task-contract-v0.1.md`](../archive/agent-contracts-legacy/task-contract-v0.1.md) (archive) là draft cũ của nền tảng TypeScript, **không** phải contract runtime.

## 1. Hai đường vào

| Đường | Khi nào | LLM | Đầu ra |
|---|---|---|---|
| **StepSpec `draft_report`** (chuẩn, production) | `ContractMessage` từ Orchestrator (bước B5) | không; tất định, chạy offline | `rp_…` + artifact `report@1`, phản hồi `AgentReport@1` |
| **Direct chat** (legacy/free-form, chỉ hỏi đáp) | mọi tin nhắn tự do | bắt buộc; `REPORT_LLM=off` → `rejected` / `LLM_REQUIRED` | câu trả lời trong `AgentReport@1`, `artifact_refs: []` |

Cả hai đường kết thúc bằng đúng một khối `AgentReport@1` (`render_agent_report`: 1–3 dòng tóm tắt tiếng Việt rồi một
JSON fence). Thành công: `state: completed` (có thể `partial: true` + `warnings`); lỗi spec: `rejected`; lỗi truy
xuất/evidence/tool/lưu: `failed`; cả hai đều có `error`. `AgentReport.state` khác trạng thái artifact `VALID`/`PARTIAL`.

| File | Vai trò |
|---|---|
| `agent.py` | entry plugin; định tuyến contract vs chat; `REPORT_LLM=off` |
| `stepspec.py`, `compose.py` | `draft_report`: resolver, sáu section, kiểm chứng, `save_report` + `artifact_put` |
| `graph.py`, `judge.py` | direct chat: LangGraph + Jev quality gate |
| `mcp_client.py`, `settings.py`, `prompts/` | MCP session, cấu hình `.env`, prompt system/compact |

## 2. StepSpec `draft_report`

**Đầu vào.** `spec.title` tùy chọn và `input_refs` ghim hash tới `insight`, `comparison`, `peer_definition`,
`chart_spec`. Chỉ đọc qua `resolve_analysis_inputs` (không tự `artifact_list`). Resolver kiểm tra quyền người dùng,
type/schema, id/version/hash, snapshot, semantic version, một dataset gốc chung và lineage comparison → peer definition.

- Cần ít nhất một trong `insight` / `comparison`, thiếu cả hai → `MISSING_INPUT`.
- Thiếu một trong hai, hoặc thiếu `chart_spec` → vẫn tạo report, artifact `PARTIAL`, giữ limitation
  (ví dụ `UPSTREAM_MISSING:chart_spec`).
- Giữ nguyên `original_question`, `run_id`, `step_id`, `idempotency_key`, snapshot, semantic; không tự điền metadata.

**Sáu section** (`compose.py::SECTION_IDS`, đúng thứ tự). Chín nhóm nội dung của quy định output được phân bổ vào
sáu section này, không phải chín section mới.

| Section | Nội dung khi có căn cứ |
|---|---|
| `context` | câu hỏi, đối tượng, phạm vi, snapshot/semantic, dataset, nguồn; thiếu metadata thì ghi "không được cung cấp" |
| `executive_summary` | kết quả chính, hàm ý/bước tiếp theo do Insight đưa ra; tách quan sát khỏi nhân quả |
| `key_metrics` | giá trị chính xác, đơn vị, N, source ref; `null` hiển thị là chưa có + limitation, không thành 0 |
| `analysis` | insight, diễn giải so sánh, khuyến nghị (cần người có thẩm quyền duyệt) |
| `evidence` | chart/table, trích dẫn; embed `{{chart_spec:<id>@<version>}}`, không vẽ lại hay tính lại |
| `limitations` | DQ/missingness chỉ khi input có, caveat snapshot/semantic, limitation upstream, cảnh báo mock, blocker B-* |

**Kiểm chứng rồi mới lưu.**

1. Mọi câu định lượng trong `statements[]` có `source_ref` = `<artifact_id>@<version>#<JSON pointer>` và
   `value_exact` khớp giá trị phân giải từ artifact đã ghim.
2. Mọi chart là input `chart_spec` đã ghim, Vega-Lite hợp lệ (`vdagent_contracts.vega_lite`), mọi `bindings[]`
   phân giải đúng. Report không tạo chart.
3. Sai bất kỳ điểm nào → `failed` / `EVIDENCE_INVALID` (hoặc mã resolver tương ứng trong catalog); không gọi
   `save_report`, không ghi `report@1`.
4. `save_report` (markdown, Backend kiểm tra embed) → `rp_…`; lỗi → `REPORT_SAVE_FAILED`.
5. `artifact_put` artifact `report@1` với `delivery.report_id`; lỗi → `TOOL_FAILED`. Markdown đã lưu có thể thành bản
   mồ côi (không có rollback).

**`report@1`**: `title`, `sections` (6), `markdown`, `statements[]` (`statement_id`, `section`, `text`, `value_exact`,
`source_ref`), `charts[]`, `tables[]`, `actions`, `validation` (kết quả + số statements/bindings/charts),
`delivery.report_id`. Envelope: producer `report`, snapshot, semantic, input refs (dataset + mọi input thực dùng),
content hash. Không đổi schema theo kiểu phá tương thích; field mới cần test consumer và duyệt của contract owner.

## 3. Direct chat (legacy/free-form)

Chỉ trả lời về nội dung đã có trong hội thoại, summary và artifact được nêu rõ. Không tạo hay lưu báo cáo/chart: báo
cáo có cấu trúc đi qua `draft_report`, biểu đồ qua Orchestrator/Chart.

- **Tool allowlist trong code** (`graph.py::ALLOWED_DIRECT_CHAT_TOOLS`): `describe_dataset`, `get_dataset_rows`,
  `artifact_get`. `send_to_agent`, `create_chart`, `save_report`, truy vấn và `artifact_list` không được cấp; id
  artifact/dataset bị giới hạn vào các id đã có trong ngữ cảnh.
- **Graph**: `agent ⇄ tools` (tool chạy song song, kết quả emit ngay) → `assess` (Jev) → `finalize`, hoặc `revise`
  **tối đa một lần** rồi quay lại `agent`. Ở bước cuối (`ctx.max_steps`) tool call bị ép thành `STEP_LIMIT_TEXT`
  (warning `STEP_LIMIT_REACHED`). Chỉ `finalize` phát câu trả lời ra ngoài.
- **Jev quality gate** (`judge.py`): OpenRouter decisions endpoint (`JEV_DECISIONS_URL`), model mặc định
  `typesafe/jev-1.13` (`JUDGE_MODEL`); hỏi `acceptable` (pass khi ≥ `PASS_THRESHOLD` 0.5) và `problem`
  (`none | missing_part | unsupported_claim | no_numbers | unclear`), tiêu chí grounded QA.
  - Jev lỗi/timeout (10 s) → coi như pass, nhưng `partial: true` + `QUALITY_GATE_UNAVAILABLE`.
  - Bị từ chối sau lần revise → `rejected` / `QUALITY_GATE_REJECTED`, draft không được phát.
- **Lỗi**: model timeout → `AgentTimeoutError`; lỗi model khác propagate; lỗi tool MCP (timeout 30 s, `is_error`)
  thành text `error: …` cho model.
- **Compaction**: `compact()` gọi model một lần với `prompts/compact.md`; không có LLM thì giữ summary cũ.
- Framework riêng của Report: `langchain_openai.ChatOpenAI` + LangGraph (không phải LiteLLM như Data/Orchestrator).

## 4. Cấu hình

`agents/report/.env` (mẫu: `.env.example`): `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`, tùy chọn `JUDGE_MODEL`,
`JEV_DECISIONS_URL`. `REPORT_LLM=off`: plugin nạp không cần key, chỉ phục vụ `draft_report`.
Quyền MCP: `mcp_tools` của plugin report trong `backend/config.yaml`.

## 5. Tài liệu sản phẩm (tham khảo, không phải contract)

- [PRD_VDAgent.docx](../product/PRD_VDAgent.docx): sáu phần báo cáo, Dashboard/PDF, completeness, human review.
- [VDAgent_Quy_dinh_Output_6_Agent.docx](../product/VDAgent_Quy_dinh_Output_6_Agent.docx): metadata/evidence/version/review,
  chín nhóm nội dung Report.
- [Báo Cáo Phân Tích Căn Hộ Bán Chậm](<../product/Báo Cáo Phân Tích Căn Hộ Bán Chậm.md>) (mẫu phân tích) và
  [Báo Cáo Thống Kê & Phân Tích Dữ Liệu Bất Động Sản](<../product/Báo Cáo Thống Kê & Phân Tích Dữ Liệu Bất Động Sản.md>)
  (mẫu DQ/audit, không phải output mặc định). Số liệu trong mẫu chỉ minh họa, không được hardcode vào output.

Thứ tự ưu tiên khi bất nhất: code/contract hiện hành và quyết định APPROVED ([decisions.md](../architecture/decisions.md))
→ PRD và quy định output → tài liệu mẫu → tài liệu legacy/draft.

## 6. Chưa triển khai / phụ thuộc tích hợp

- **Review workflow** (`DRAFT`, `READY_FOR_REVIEW`, `IN_REVIEW`, `APPROVED`, `REJECTED`, khóa version): chưa có trong
  Report hay Backend. Report không tự gán hay chuyển trạng thái review.
- **Dashboard / PDF**: Backend có `GET` report và `GET /api/chart-specs/{id}/{version}`; chưa có route PDF/review.
  Renderer phải chiếu đúng `report@1` đã lưu, không tính lại. Report không được báo PDF đã tạo hay report đã duyệt.
- Báo cáo hoàn tất không có nghĩa đã được duyệt hay phát hành.

## 7. Kiểm thử

`agents/report/vdagent_report/tests/` (fake LLM/MCP/Jev, không cần key): envelope `AgentReport@1`, định tuyến,
allowlist tool chặn ở code, `REPORT_LLM=off`, kiểm chứng evidence, `MISSING_INPUT`/`PARTIAL`, lỗi lưu, tương thích
payload. Golden end-to-end: [e2e-golden.md](../testing/e2e-golden.md).
