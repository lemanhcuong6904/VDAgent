VDAgent · Orchestrator → Report Task Contract · v0.1

> **Cảnh báo (30/09/2026):** đây là draft cũ, dựa trên kiến trúc TypeScript + semantic layer phía
> Data — semantic layer đó đã bị xóa trong refactor sang Python/MCP. Một số trường như
> `semantic_config_version`, `snapshot_refs` có thể không còn áp dụng với code hiện tại. Xem
> [docs/agents/report.md](../../agents/report.md) để biết kiến trúc Report Agent hiện hành (LangGraph + Jev judge, nhận
> input qua message tự do trong `ctx.history`, không nhận `ReportStepSpec` có cấu trúc). Cần
> Orchestrator/Data team xác nhận lại contract này trước khi dùng.

#### VDAgent

# ORCHESTRATOR → REPORT AGENT

## TASK / STEPSPEC CONTRACT

Version 0.1 · Draft để owner Orchestrator kiểm tra field

**Mục tiêu tài liệu**

• Tài liệu này không thay thế toàn bộ Orchestrator design. Nó chỉ chốt phần interface mà Report Agent cần từ Orchestrator để bắt đầu tạo Draft Report. • Các field được chia thành: Required / Optional / Conditional và PRD-derived / Design proposal. • Những chỗ PRD chưa khóa được đánh dấu OPEN QUESTION để người làm Orchestrator xác nhận tên field, ownership và state hiện có trong codebase.

### 1. Bối cảnh từ PRD

- Orchestrator chịu trách nhiệm hiểu intent, xác định scope, tạo execution plan, phân rã task, quản lý dependency, theo dõi status, retry và recovery; không trực tiếp query/tính business metric.

- Output chính của Orchestrator là Execution Plan, Agent Tasks, dependency graph và run/task status.

- Report Agent nằm ở cuối flow, tổng hợp các artifact hợp lệ và kiểm tra completeness trước khi tạo report.

- Theo failure policy: Orchestrator/Data là critical path; Compare/Insight/Chart có thể fail độc lập và report cuối có thể PARTIAL nếu thiếu thành phần.

### 2. Luồng Orchestrator → Report Agent

```
Compare / Insight / Chart complete or reach terminal state
                    ↓
              Orchestrator
        checks dependency / policy
                    ↓
       creates REPORT_GENERATION task
                    ↓
            sends ReportStepSpec
                    ↓
              Report Agent
      loads / validates input artifacts
                    ↓
          Draft Report 6 sections
                    ↓
         status + artifact returned
                    ↓
              Human Review
```

_Điểm cần chốt: Report có nhận trực tiếp danh sách artifact IDs từ Orchestrator hay chỉ nhận run_id rồi tự query Shared Artifact Store._

### 3. Draft ReportStepSpec

|**Field**|**Type**|**Requirement**|**Basis**|**Ý nghĩa / cần check**|
|---|---|---|---|---|
|run_id|string|Required|PRD-derived|ID toàn bộ investigation/run;<br>Report chỉ ghép artifact cùng<br>run.|



Draft for Team A / Orchestrator Review

|**Field**|**Type**|**Requirement**|VDAgent·Orchest<br>**Basis**|rator→Report Task Contract·v0.1<br>**Ý nghĩa / cần check**|
|---|---|---|---|---|
|task_id|string|Required|PRD-derived|ID task tạo report.|
|step_type|enum|Required|Design proposal|Đề xuất cố định<br>REPORT_GENERATION để<br>route đúng handler.|
|intent|enum/string|Required|PRD-derived|SLOW_MOVING_INVESTIG<br>ATION |<br>PEER_GROUP_COMPARIS<br>ON |<br>PERFORMANCE_METRIC_<br>LOOKUP.|
|scope|object|Required|PRD-derived|Scope đã resolve; Report<br>không tự hiểu lại scope từ<br>free-text.|
|scope.market_id|string|Optional|Design proposal|Có khi analysis cần Market<br>level.|
|scope.project_id|string|Conditional|Design proposal|Bắt buộc nếu run đã resolve<br>project.|
|scope.zone_id|string|Optional|Design proposal|Zone/Area scope nếu có.|
|scope.unit_ids|string[]|Optional|Design proposal|Một hoặc nhiều unit mục tiêu.|
|user_query|string|Optional|Open question|Giữ câu hỏi gốc để<br>trace/narrative context; không<br>dùng để override structured<br>scope.|
|audience|string[]|Optional|Open question|Sales Operations / Sales<br>Manager / Project Director;<br>cần Section 2 nếu team<br>muốn truyền từ Orchestrator.|
|requested_language|string|Optional|Design proposal|Ngôn ngữ report; có thể<br>default theo<br>conversation/user.|
|requested_outputs|string[]|Optional|Open question|WEB | PDF; POC yêu cầu cả<br>Web/PDF nhưng cần chốt có<br>phải field task không.|
|required_sections|string[]|Optional|Open question|Có cần gửi 6 section hay<br>Report Template hard-code 6<br>phần?|
|required_artifact_refs|string[]|Conditional|Open question|Danh sách artifact bắt buộc<br>nếu Orchestrator là owner<br>của input resolution.|
|optional_artifact_refs|string[]|Optional|Open question|Chart/supporting artifacts có<br>thể thiếu mà vẫn chạy<br>PARTIAL.|
|upstream_status|object|Required|PRD-derived|Tóm tắt terminal status<br>Data/Compare/Insight/Chart<br>để Report biết<br>degraded/partial path.|
|missing_components|string[]|Conditional|Design proposal|Bắt buộc khi upstream_status<br>có failed/missing component.|
|snapshot_refs|string[]|Conditional|Open question|Dùng để enforce snapshot<br>consistency nếu Orchestrator<br>đang giữ run snapshot.|
|semantic_config_version|string|Conditional|Open question|Dùng để enforce semantic<br>consistency nếu Orchestrator<br>quản lý version của run.|
|access_scope_ref|string|Optional|Design proposal|Opaque ref tới authorization<br>scope thay vì copy toàn bộ<br>permission.|
|report_version_base|number|null|Optional|Design proposal|Dùng khi regenerate/revision<br>sau review.|
|trigger_reason|enum|Optional|Design proposal|INITIAL | RETRY |<br>REVIEW_REVISION |<br>REGENERATE.|
|attempt|number|Optional|Design proposal|Số lần chạy task hiện tại.|



Draft for Team A / Orchestrator Review

||||VDAgent·Orchestrator|→Report Task Contract·v0.1|
|---|---|---|---|---|
|**Field**|**Type**|**Requirement**|**Basis**|**Ý nghĩa / cần check**|
|timeout_ms|number|Optional|Design proposal|Operational timeout nếu<br>Orchestrator truyền xuống.|



**OPEN QUESTION QUAN TRỌNG CHO OWNER ORCHESTRATOR**

- Có nên truyền required_artifact_refs/optional_artifact_refs trực tiếp không? Nếu không, Report sẽ query Shared Artifact Store theo run_id.

- scope schema thực tế trong Oces hiện đang dùng field nào: project_id / zone_id / unit_ids hay một generic entity scope? • audience, requested_outputs và required_sections có nằm trong task spec hay thuộc Report config/template? • snapshot_refs và semantic_config_version nằm ở Orchestrator run context hay chỉ nằm trong Data/Artifact layer?

### 4. Draft upstream_status / dependency summary

Report cần biết upstream đang complete hay degraded để quyết định COMPLETE/PARTIAL và hiển thị limitation. Tên enum dưới đây là draft, cần map vào state machine thật của Oces.

|**Field**|**Type**|**Requirement**|**Ý nghĩa**|
|---|---|---|---|
|upstream_status.data|enum|Required|Data là critical path; nếu FAILED<br>thì không trigger Report.|
|upstream_status.compare|enum|Required|Có thể VALID / PARTIAL / FAILED /<br>SKIPPED theo policy.|
|upstream_status.insight|enum|Required|Có thể VALID / PARTIAL / FAILED /<br>SKIPPED theo policy.|
|upstream_status.chart|enum|Required|Có thể VALID / PARTIAL / FAILED /<br>SKIPPED theo policy.|
|missing_components|string[]|Conditional|Ví dụ ['chart']; dùng cho<br>limitation/completeness.|
|failure_refs|string[]|Optional|Ref tới task/error logs để audit,<br>không bắt buộc cho narrative.|



##### Policy cần Oces xác nhận

- Orchestrator/Data FAILED → không trigger Report vì critical path không đáng tin cậy.

- Compare/Insight/Chart FAILED → có thể vẫn trigger Report nếu policy cho phép; Report phải được biết component nào thiếu để đánh PARTIAL.

- Cần chốt exact terminal task states: COMPLETED/PARTIAL/FAILED/SKIPPED hay enum khác trong codebase.

### 5. Hai phương án truyền input artifact

|**Phương án**|**Ví dụ**|**Ưu điểm**|**Điểm cần chốt**|
|---|---|---|---|
|A. Oces gửi artifact IDs|required_artifact_refs: [METRIC_1,<br>DQ_1, CMP_1, INS_1]; optional:<br>[CHART_1]|Report deterministic hơn; biết<br>chính xác input của task.|Oces phải resolve artifact/version<br>trước khi dispatch.|
|B. Oces chỉ gửi run_id|run_id: RUN_001|Oces payload gọn; Report tự<br>discovery.|Report phải query/filter<br>version/status; logic coupling với<br>Artifact Store lớn hơn.|



_Đề xuất ban đầu: ưu tiên phương án A cho POC nếu Orchestrator đã nắm artifact status/IDs, vì dễ test fixture và replay một run cụ thể. Đây là design proposal, không phải PRD requirement._

Draft for Team A / Orchestrator Review

VDAgent · Orchestrator → Report Task Contract · v0.1

### 6. Ví dụ ReportStepSpec để teammate Oces review

```json
{
  "run_id": "RUN_20260921_REALESTATE_01",
  "task_id": "TASK_REPORT_001",
  "step_type": "REPORT_GENERATION",
  "intent": "SLOW_MOVING_INVESTIGATION",
  "scope": {
    "project_id": "PRJ_X",
    "zone_id": "ZONE_X",
    "unit_ids": [
      "U_A12_08"
    ]
  },
  "user_query": "Tại sao căn A12-08 bán chậm?",
  "audience": [
    "SALES_OPERATIONS",
    "SALES_MANAGER"
  ],
  "requested_language": "vi",
  "requested_outputs": [
    "WEB",
    "PDF"
  ],
  "required_artifact_refs": [
    "METRIC_DOM_001",
    "DQ_001",
    "CMP_PRICE_001",
    "INS_PRICE_001"
  ],
  "optional_artifact_refs": [
    "CHART_DOM_001"
  ],
  "upstream_status": {
    "data": "VALID",
    "compare": "VALID",
    "insight": "VALID",
    "chart": "PARTIAL"
  },
  "missing_components": [],
  "snapshot_refs": [
    "SNAP_20260921"
  ],
  "semantic_config_version": "sem-1.2.0",
  "report_version_base": null,
  "trigger_reason": "INITIAL",
  "attempt": 1
}
```

### 7. Validation rules phía Report dự kiến áp dụng

- run_id và task_id phải tồn tại.

- intent phải thuộc intent mà POC hỗ trợ.

- scope phải resolve được target của run; Report không tự sửa scope.

- Nếu Data/Orchestrator critical path failed thì Report task không nên được dispatch.

- Nếu analytical agent failed/partial thì upstream_status phải phản ánh rõ; Report không được che giấu.

- Nếu Oces gửi artifact refs, tất cả required refs phải resolve được; optional refs có thể thiếu theo policy.

- Artifact dùng cho cùng report phải cùng run_id; snapshot/semantic version mismatch phải bị cảnh báo hoặc reject theo policy.

- Report chỉ consume artifact VALID hoặc PARTIAL được policy cho phép; không dùng DRAFT/INVALID/SUPERSEDED.

### 8. Report Agent trả gì lại cho Orchestrator?

Phần này cũng cần owner Oces check vì Orchestrator theo dõi task/run status.

|**Field**|**Type**|**Requirement**|**Ý nghĩa**|
|---|---|---|---|
|run_id|string|Required|Run tương ứng.|
|task_id|string|Required|Report task ID.|



Draft for Team A / Orchestrator Review

|||VDAgent|·Orchestrator→Report Task Contract·v0.1|
|---|---|---|---|
|**Field**|**Type**|**Requirement**|**Ý nghĩa**|
|task_status|enum|Required|Đề xuất COMPLETED | PARTIAL |<br>FAILED.|
|report_artifact_id|string|null|Conditional|Có nếu đã persist report artifact.|
|report_version|number|null|Conditional|Version của report artifact.|
|completeness_status|enum|Required|COMPLETE | PARTIAL | INVALID<br>(draft enum).|
|missing_sections|string[]|Optional|Các section thiếu nếu partial.|
|limitations|string[]|Conditional|Bắt buộc nếu PARTIAL.|
|error_code|string|null|Conditional|Nếu FAILED.|
|error_message|string|null|Conditional|Nếu FAILED.|
|web_report_ref|string|null|Optional|Ref/route metadata cho Web<br>report.|
|pdf_report_ref|string|null|Optional|Ref tới PDF nếu render thành<br>công.|



### 9. Checklist gửi bạn làm Oces check

- ☐ Trong schema task hiện tại đã có run_id / task_id / step_type chưa? Tên field có khác không?

- ☐ intent enum hiện tại dùng tên gì? Có đúng 3 intent của POC không?

- ☐ scope hiện tại biểu diễn project/zone/unit thế nào? Có generic target/entity scope không?

- ☐ Oces sẽ gửi artifact IDs cho Report hay Report tự query theo run_id?

- ☐ State enum thật của task/upstream là gì? Mapping sang VALID/PARTIAL/FAILED như thế nào?

- ☐ Khi Compare/Insight/Chart fail, điều kiện chính xác nào vẫn cho phép trigger Report?

- ☐ snapshot_ref và semantic_config_version có nằm trong execution plan/run context không?

- ☐ audience / requested_outputs / required_sections có cần ở StepSpec hay Report tự lấy từ config?

- ☐ Retry: Oces có truyền attempt/timeout/trigger_reason không?

- ☐ Report trả task completion về Oces bằng event/payload nào? Tên field/status hiện tại là gì?

- ☐ Regenerate sau Human Review dùng task mới hay cùng task + report_version_base?

### 10. Điểm cần freeze trước khi Report Team code fixture

- Tên field tối thiểu: run_id, task_id, intent, scope, upstream status.

- Cách truyền/resolve artifact refs.

- Task state enum + trigger policy cho PARTIAL/FAILED upstream.

- Snapshot/semantic version ownership.

- Payload Report trả lại Oces khi COMPLETED/PARTIAL/FAILED.

Draft for Team A / Orchestrator Review

