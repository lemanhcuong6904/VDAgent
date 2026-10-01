# Report Agent — đặc tả triển khai chat riêng và Orchestrator

Cập nhật: 30/09/2026. Tài liệu này là đặc tả triển khai Report Agent trên kiến trúc Python hiện tại. Contract có hiệu lực là `StepSpec@1`, phản hồi worker `AgentReport@1`, catalog `contracts/vdagent_contracts/catalogs/report.json` và artifact `report@1`. Không dùng `task-contract-v0.1.md` hoặc tài liệu TypeScript cũ làm contract runtime.

## 1. Mục tiêu và phạm vi

Report có hai cách sử dụng, nhưng cùng ranh giới bằng chứng:

1. **Chat riêng:** trả lời câu hỏi về nội dung trong hội thoại hiện tại, bản tóm tắt hội thoại và artifact mà người dùng/Orchestrator đã cung cấp hoặc Report đã nhận hợp lệ trong chính lượt này.
2. **Orchestrator:** nhận `StepSpec@1` operation `draft_report`, đọc các artifact được ghim, tạo báo cáo sáu phần có thể kiểm chứng, lưu `report@1` và bản markdown `rp_…`.

Report chịu trách nhiệm trình bày, định dạng và giải thích kết quả có sẵn. Data chịu trách nhiệm lấy dữ liệu; Insight phân tích yếu tố; Compare tạo phép so sánh; Chart tạo đặc tả biểu đồ. Report không tự chạy truy vấn hoặc phân tích mới, không chọn thêm tập dữ liệu, không gọi agent khác để lấp chỗ trống và không biến tương quan thành kết luận nhân quả.

Trong phạm vi này, mở rộng đầu ra cuối của chat riêng thành `AgentReport@1` như đầu ra StepSpec. Không thay schema dùng chung, enum `AgentReport.state`, catalog operation hoặc API Backend. Việc Dashboard/PDF và review workflow là phần phối hợp Backend/Frontend theo mục 8, không được giả định đã có trong Report Agent.

## 2. Contract vào/ra

### 2.1 Đầu vào Orchestrator

- Parser chung đọc `StepSpec@1`; Report chỉ hỗ trợ operation `draft_report` với `spec.title` tùy chọn và `input_refs` cho dataset cùng các artifact phân tích/biểu đồ có mặt.
- Catalog hiện quy định các loại có thể dùng: `insight`, `comparison`, `peer_definition`, `chart_spec`. Dataset gốc được resolver suy ra/kiểm tra cùng các ref đó.
- Dùng `resolve_analysis_inputs` và resolver chung, không tự `artifact_list` để tìm nguồn thay cho ref bị thiếu. Mỗi ref phải đúng quyền người dùng, ID/version/hash, snapshot, semantic version, dataset gốc và lineage theo contract hiện hành. Mọi input trong report phải cùng một dataset, snapshot và semantic version; comparison phải khớp peer definition được ghim.
- Phải có ít nhất một trong `insight` hoặc `comparison`; resolver từ chối nếu thiếu cả hai (`MISSING_INPUT`). Một trong hai có thể vắng mặt và report vẫn được tạo `PARTIAL`; `chart_spec` có thể vắng mặt nhưng limitation `UPSTREAM_MISSING:chart_spec` phải được giữ. `peer_definition` được dùng khi có trong input, thường đi cùng comparison.
- Giữ nguyên `original_question`, `run_id`, `step_id`, `idempotency_key`, snapshot và semantic version nếu có trong StepSpec. Không tự điền metadata không được caller cung cấp hoặc resolver xác nhận.
- Input sai contract/spec trả `AgentReport@1` `rejected` với `error`; lỗi truy xuất/evidence/tool/persistence trả `failed` với `error`. Tuân thủ `error_codes` trong catalog Report.

### 2.2 Output chung

- Mỗi phản hồi cuối của Report trên cả hai đường phải có đúng một khối JSON `AgentReport@1`, theo `render_agent_report`: 1–3 dòng tóm tắt tiếng Việt rồi một JSON fence. Đây là envelope phản hồi chung, không phải nơi nhét toàn bộ nội dung báo cáo.
- `summary` chứa tóm tắt tiếng Việt cho caller. `artifact_refs` chỉ chứa ref artifact có thật, đã được tạo/nhận diện và xác thực; không bịa ID. Chat không gắn `run_id`/`step_id` nếu lượt gọi không có chúng.
- Lượt thành công dùng `state: completed`; thất bại/từ chối dùng `failed`/`rejected` và `error` bắt buộc; thiếu thông tin thực sự cần người dùng bổ sung có thể dùng `input_required` cùng `question`. `partial` và `warnings` phản ánh đúng trạng thái output.
- Phản hồi StepSpec thành công giữ metadata điều phối, snapshot/semantic, warnings và `partial` như hiện tại; `artifact_refs` trỏ đến artifact `report@1` được tạo. `summary` nêu `rp_…` trong `delivery.report_id` và số validation phù hợp.
- Không thay `contracts/vdagent_contracts/reports.py`. Dùng `render_agent_report` / `parse_agent_report`; lỗi không được giả dạng `completed`.

### 2.3 Artifact `report@1` hiện hành

Giữ tất cả field và ý nghĩa đang được consumer dùng trong [CANONICAL_DATA_CONTRACT §9](../../integration/CANONICAL_DATA_CONTRACT.md#9-ws6-report1-implemented-verified-offline):

`title`, `sections` (đúng sáu section), `markdown`, `statements[]` (`statement_id`, `section`, `text`, `value_exact`, `source_ref`), `charts[]`, `tables[]`, `actions`, `validation` (result và số đếm statements/chart bindings/charts), `delivery.report_id`.

Envelope phải giữ `schema_version: report@1`, producer `report`, status artifact `VALID`/`PARTIAL`, snapshot, semantic version, input refs, content hash và lineage do artifact store tạo/kiểm tra. `input_artifact_refs` gồm dataset gốc và mọi input phân tích/biểu đồ thực sự dùng. Giới hạn từ input được bảo toàn; upstream tùy chọn vắng mặt làm report `PARTIAL`, không được che giấu.

Không thay schema `report@1` theo cách phá tương thích. Trường nghiệp vụ bổ sung từ quy định output chỉ được thêm theo kiểu tương thích và phải có test consumer; nếu yêu cầu bắt buộc không thể biểu diễn tương thích, dừng thay đổi schema và xin quyết định contract/version riêng, không tự đổi version trong task này.

## 3. Chat riêng: hành vi bắt buộc

### 3.1 Nguồn được phép và giới hạn tool

- Nguồn trả lời là nội dung user cung cấp, lịch sử/summary của chính hội thoại, kết quả tool đã được cung cấp trong hội thoại và artifact ID được caller đưa rõ ràng hoặc đã xuất hiện trong lượt này. Quyền đọc artifact vẫn phải được Backend xác thực.
- Không gọi `send_to_agent` trong chat riêng. Không gọi `run_query`, `re_run_query`, `list_tables`, `artifact_list` hoặc chức năng khám phá để tìm nguồn thay cho ref bị thiếu.
- Không tự lấy các hàng dữ liệu chỉ vì tool `get_dataset_rows` được cấp. Chỉ đọc artifact/dataset đã nêu rõ trong đầu vào và khi câu hỏi đòi hỏi diễn giải nội dung đó; không mở rộng sang dataset khác hoặc phạm vi khác.
- Trong chế độ hỏi đáp, `artifact_get` chỉ được gọi với ID/version đã có trong ngữ cảnh; `describe_dataset`/`get_dataset_rows` chỉ được gọi khi user chỉ rõ dataset và hỏi nội dung của nó. Không gọi `create_chart` hay `save_report` trong chế độ hỏi đáp. Tạo/lưu báo cáo thuộc operation `draft_report`; tạo chart thuộc Chart agent.
- Tool permission là kiểm soát ở Backend; prompt không thay thế kiểm soát quyền. Nếu runtime vẫn cung cấp `send_to_agent` cho Report thì Report không dùng nó cho chế độ chat riêng; task triển khai phải bổ sung kiểm soát ở entry/graph để nhánh direct-chat không đăng ký hoặc không thể gọi tool này. Nhánh StepSpec deterministic không dùng peer tools.

### 3.2 Cách trả lời

- Trả lời câu hỏi dựa đúng vào nguồn hiện có; giữ chính xác số, đơn vị, mẫu số, khoảng thời gian và caveat nguồn.
- Nếu user hỏi điều chưa có trong nguồn hoặc cần phân tích/lấy dữ liệu mới, trả lời phần có căn cứ, chỉ rõ điều không thể xác nhận và nêu dữ liệu/kết quả còn thiếu. Không suy diễn nguyên nhân, không bịa số, định nghĩa, link, artifact ID, dữ liệu DQ hay kết quả từ agent khác.
- Câu trả lời vẫn đóng gói thành một `AgentReport@1`; nếu không có artifact mới thì `artifact_refs: []`. Nếu từ chối vì ngoài phạm vi, dùng `rejected` và `error` rõ nguyên nhân. Nếu nguồn thiếu nhưng vẫn trả lời hữu ích được, có thể `completed` với `partial: true` và warning/giới hạn trong `summary`.
- Đầu ra cuối của graph qua Jev quality gate với tiêu chí grounded QA (không bắt buộc tạo chart/report ID hoặc nêu số khi nguồn không có). Sau khi Jev trả verdict, code phải dựng `AgentReport` rồi gọi `render_agent_report`; không yêu cầu model tự viết JSON envelope. Phần văn bản trước fence cũng là tóm tắt tiếng Việt của draft. Không trích artifact ID từ regex hoặc câu trả lời model để tự tạo `ArtifactRef` vì ID không đủ version/hash. Jev không khả dụng được coi là pass để không chặn chat, nhưng phải gắn `partial: true` và warning `QUALITY_GATE_UNAVAILABLE`; đây không phải bằng chứng nội dung đã được kiểm chứng. Nếu Jev từ chối sau lần revise được phép, trả `rejected` kèm `QUALITY_GATE_REJECTED`, không phát draft bị từ chối ra ngoài. Giữ lỗi model/tool theo cơ chế hiện hành.

### 3.3 Khi `REPORT_LLM=off`

- `StepSpec@1 draft_report` tiếp tục chạy offline, tất định, không LLM/Jev.
- Free text phải trả một `AgentReport@1` parse được, `state: rejected`, `error.code` ổn định (đề xuất `LLM_REQUIRED`) và thông báo tiếng Việt rằng chat hỏi đáp cần cấu hình LLM; không emit `NO_LLM_TEXT` dạng plain text.
- `compact()` khi không có LLM tiếp tục giữ summary trước đó.

## 4. Orchestrator: `draft_report`

### 4.1 Tạo nội dung sáu phần

Giữ đúng section ID, thứ tự và title hiện có tại `agents/report/vdagent_report/compose.py::SECTION_IDS/SECTION_TITLES`: `context`, `executive_summary`, `key_metrics`, `analysis`, `evidence`, `limitations`. Sáu section là yêu cầu PRD/checklist và khớp code. Danh sách 9 loại nội dung trong quy định output là nội dung cần được phân bổ vào sáu section, không phải chín section mới.

| Section hiện tại | Nội dung bắt buộc khi có căn cứ |
|---|---|
| `context` | Câu hỏi/mục tiêu, đối tượng, audience nếu caller cung cấp, phạm vi được cấp, kỳ báo cáo nếu nguồn nêu, snapshot/semantic, dataset và danh sách nguồn. Không có metadata thì ghi không được cung cấp; không tự đặt. |
| `executive_summary` | Kết quả chính, metric có ý nghĩa và hàm ý/bước tiếp theo nếu Insight đưa ra; phân biệt observation với causal claim. |
| `key_metrics` | Data findings/metrics và benchmark có sẵn; giá trị chính xác, đơn vị, population/N, định nghĩa/cách tính nếu nguồn có, source ref. Giá trị null/unavailable hiển thị là chưa có và limitation, không chuyển thành 0. |
| `analysis` | Insight, comparison interpretation và recommendation từ upstream; giữ caveat/confidence nếu có. Recommendation là đề xuất cần người có thẩm quyền phê duyệt, không phải hành động đã thực hiện. |
| `evidence` | Chart/table, source index/citations, phương pháp được upstream mô tả. Giữ chart embed `{{chart_spec:<artifact_id>@<version>}}`; không vẽ lại hoặc tái tính dữ liệu. |
| `limitations` | DQ và missingness chỉ khi input cung cấp; snapshot/semantic caveat, upstream limitations, synthetic/mock warnings, B-blocker liên quan và điều chưa thể kết luận. Không tuyên bố đã chạy các kiểm tra DQ không có trong input. |

`audience`, objective chi tiết, reporting period, KPI target, owner của action và methodology chỉ được điền nếu có trong request hoặc artifact. Mẫu báo cáo không cấp dữ liệu mặc định để điền.

### 4.2 Kiểm chứng bằng chứng và lưu trữ

- Mỗi số liệu/câu định lượng trong `statements[]` phải mang `source_ref` dạng `<artifact_id>@<version>#<RFC6901-pointer>` và `value_exact` khớp giá trị phân giải từ artifact đã ghim. Kiểm lại toàn bộ statements trước khi lưu.
- Mọi chart phải là input `chart_spec` đã ghim. Xác thực schema/Vega-Lite `$schema`, từng `bindings[].source_ref`, `value_exact`, unit và source value. Không tạo chart mới trong nhánh StepSpec. Embed phải trỏ đúng `chart_spec:<id>@<version>`.
- Evidence sai, ref không phân giải, hash/snapshot/semantic/lineage sai hoặc binding sai: trả `failed` với mã catalog thích hợp (đặc biệt `EVIDENCE_INVALID` cho evidence sai), không gọi `save_report`, không `artifact_put` report và không phát `artifact_refs` report.
- Chỉ sau khi validate thành công mới gọi `save_report`; sau đó ghi artifact `report@1` chứa `delivery.report_id` trả về. Nếu lưu markdown thất bại: `REPORT_SAVE_FAILED`; nếu tạo artifact thất bại sau khi markdown đã lưu, trả lỗi thất bại và không tuyên bố hoàn tất. Ghi rõ khả năng có bản markdown mồ côi nếu tool không hỗ trợ rollback; không bịa cách rollback.
- `VALID` chỉ khi đầy đủ theo contract và không có limitation khiến output partial. `PARTIAL` khi thiếu artifact upstream tùy chọn hoặc limitation upstream được giữ lại. Partial vẫn có thể là kết quả `completed` với `partial: true`; đây không phải review approval.
- Báo cáo hoàn tất không có nghĩa đã được người dùng duyệt, phát hành hay đã có PDF.

## 5. Báo cáo mẫu và quy định output: cách áp dụng

Hai file mẫu trong `docs/` được đọc và dùng làm tham khảo nội dung, không phải contract hoặc dữ liệu đầu vào:

- **Báo Cáo Phân Tích Căn Hộ Bán Chậm** trình bày mục tiêu/KPI, findings, insights, recommendation theo owner, scope/audience/run context và caveat dữ liệu trong layout sáu phần. Dùng các nội dung đó theo mapping ở mục 4.1; không bắt buộc tái tạo nguyên văn heading riêng “Objectives & KPIs”, “Recommendations”, “Appendix”.
- **Báo Cáo Thống Kê & Phân Tích Dữ Liệu Bất Động Sản** là mẫu báo cáo Data Quality/audit: snapshot/semantic, null/integrity/constraint checks, thống kê/phân phối/outlier/drift/preprocessing. Đây không phải output mặc định của Report. Chỉ đưa các kết quả đó vào `limitations`/`evidence` khi Data hoặc artifact đầu vào đã cung cấp; không tính lại.
- Tất cả số, tên căn/dự án, nhận định và khuyến nghị trong mẫu là minh họa. Thêm test regression để bảo đảm các giá trị mẫu không bị hardcode vào output.

Quy định `VDAgent_Quy_dinh_Output_6_Agent.docx` có hai lớp: checklist yêu cầu sáu section và danh sách chín nhóm nội dung trình bày. Giải quyết bằng sáu section code hiện hành và mapping bên trên. Yêu cầu artifact có metadata/hash/lineage/limitations áp dụng qua envelope hiện hành; không tạo envelope riêng cho Report.

## 6. Chat answer và artifact report khác nhau

- `AgentReport@1` là phản hồi của một lần gọi agent. `report@1` là artifact nghiệp vụ đã lưu. Một câu chat đáp về artifact có sẵn không tự tạo report mới; khi đã tạo report, ref phải trỏ đúng artifact `report@1`, còn `rp_…` là ID từ delivery `save_report`.
- Trạng thái thực thi `AgentReport.state` (`completed`, `input_required`, `failed`, `rejected`, `canceled`) khác với envelope artifact `VALID`/`PARTIAL`.
- Tài liệu output định nghĩa review status `DRAFT`, `READY_FOR_REVIEW`, `IN_REVIEW`, `APPROVED`, `REJECTED`, content hash locking và bất biến version. Code hiện tại/Backend API chưa triển khai transition/API review. Report task chỉ được ghi nhận `DRAFT`/`READY_FOR_REVIEW` trong `report@1` nếu field đó được thêm tương thích và được contract owner duyệt; không giả trạng thái `IN_REVIEW`/`APPROVED`/`REJECTED`, không tự chuyển state qua lời agent. `READY_FOR_REVIEW` chỉ được đặt sau completeness/evidence gate thành công và phải gắn đúng content hash artifact store trả về; nếu không thể làm đúng hash do thứ tự tạo artifact thì để `DRAFT` và bàn giao Backend.
- Không cập nhật artifact đã tạo tại chỗ. Review, khóa version, supersedes/version history và trạng thái sau review thuộc Backend/review service. Chưa có API/version family thì Report không tự phát minh quy tắc ID/version hoặc endpoint.

## 7. Kế hoạch thay đổi theo file

1. **`agents/report/vdagent_report/agent.py`**: định tuyến ContractMessage như hiện tại; đóng gói unsupported/invalid StepSpec và `REPORT_LLM=off` free text bằng `render_agent_report`; chỉ emit một phản hồi cuối theo envelope. Không đổi metadata có sẵn.
2. **`agents/report/vdagent_report/graph.py` / `agent.py`**: thêm chế độ direct-chat (flag/turn context tách biệt StepSpec) để `send_to_agent` không được cấp/call; không làm suy giảm khả năng xử lý tool trung gian còn lại. Thêm allowlist/guard trước khi gọi tool cho direct-chat theo 3.1, giới hạn artifact/dataset IDs về những ID caller cung cấp/đã hiện diện trong context. Nếu runtime không thể xác định call type/source an toàn, từ chối tool call thay vì suy đoán.
3. **`agents/report/vdagent_report/prompts/system.md`**: ghi rõ grounded QA, ranh giới giữa giải thích và phân tích mới, định dạng `AgentReport@1`, báo thiếu căn cứ, không lưu report/chart nếu user chưa yêu cầu, không lộ số/ID ngoài nguồn. Prompt chỉ hướng dẫn; enforce tool boundary trong code.
4. **`agents/report/vdagent_report/stepspec.py` / `compose.py`**: giữ resolver/validator hiện tại; sửa nội dung section chỉ để khớp mapping 4.1 và đảm bảo limitations/metadata từ input được giữ. Giữ nguyên sáu ID, title, field payload hiện tại. Bổ sung field output mới chỉ khi đã xác định tương thích và có schema/consumer test.
5. **`agents/report/vdagent_report/tests/`**: thêm unit tests cho serializer, mode routing, tool boundary, evidence gating, missing-source behavior và payload compatibility. Dùng fake LLM/MCP/Jev; không cần key thật.
6. **`docs/agent-a/report/design.md` / README**: sau khi hành vi được đổi, cập nhật mô tả runtime để bỏ thông tin cũ (ví dụ free-text output thuần hoặc khả năng peer được cấp) và trỏ tới spec này.

Không chỉnh `AgentReport@1`, Backend API, catalog `draft_report`, `task-contract-v0.1.md` để giả vờ đây là contract đang chạy. Nếu phát hiện thay đổi không tương thích cần thiết, dừng phần đó và báo đúng gap cho contract owner.

## 8. Dashboard, PDF và review — phụ thuộc tích hợp

PRD POC yêu cầu Dashboard và PDF, kiểm tra completeness trước review, và có người review trước khi hoàn tất; Report Agent hiện mới lưu markdown cùng `report@1` và embed chart. API doc FE v0.3 ghi A12/A13/A16/A17 là draft/TBD; Backend hiện có report GET và chart-spec GET, chưa có route PDF/review. Vì vậy:

- Report Agent tạo một nguồn nội dung chuẩn (`report@1` + markdown) và cung cấp cùng version/hash/snapshot cho renderer. Renderer Dashboard/PDF phải chiếu đúng dữ liệu đã lưu, không query hoặc tính lại metric.
- **Backend/Frontend follow-up bắt buộc cho nghiệm thu POC end-to-end:** xác định và triển khai API/read model cho Dashboard, PDF, completeness/review, cùng kiểm thử hai format lấy đúng cùng report version, content hash và snapshot. Không đặt tên endpoint hay schema mới trong spec này; API draft không phải contract đã chốt.
- Report Agent không được báo PDF đã tạo, review đã hoàn tất hoặc report đã approved khi chưa có phản hồi xác thực từ thành phần sở hữu chức năng đó. Thiếu renderer/review API là integration blocker để tuyên bố POC delivery/review hoàn chỉnh, không phải lý do để tự thêm API vào plugin.

## 9. Kiểm thử và nghiệm thu

### 9.1 Chat riêng

- Thành công trả text có đúng một JSON fence, parse bằng `parse_agent_report`, contract đúng `AgentReport@1`; không có artifact mới thì refs rỗng.
- Hỏi số liệu/claim có trong context: trả lời chính xác cả value/unit/source caveat. Hỏi số liệu không có, dữ liệu mới hoặc nguyên nhân chưa được xác lập: nêu giới hạn, không bịa và không đổi `null` thành 0.
- Xác nhận direct-chat không gọi `send_to_agent`, `run_query`, `re_run_query`, `artifact_list`; không đọc ID/dataset không được user hoặc hội thoại hiện tại cung cấp. Có kiểm thử tool-call bị chặn ở code, không chỉ assert prompt.
- Chat hỏi đáp không gọi `save_report`/`create_chart`; yêu cầu tạo báo cáo cấu trúc phải đi qua `draft_report`, yêu cầu tạo biểu đồ phải được chuyển về luồng Orchestrator/Chart.
- `REPORT_LLM=off`: free text là `rejected` với `error`, đúng `AgentReport@1`; cùng cấu hình đó, valid `draft_report` offline vẫn chạy.
- Kiểm thử rejected/failed/input_required consistency, model/tool/Jev errors và không emit hai phản hồi cuối.

### 9.2 StepSpec và bằng chứng

- Golden StepSpec giữ `report@1` hợp lệ, đúng sáu section ID/thứ tự, `rp_…`, input refs, lineage, limitations, validation.
- Mọi số trong `statements` resolve chính xác theo `source_ref`; mọi chart binding resolve chính xác và schema chart hợp lệ. Không có số liệu của báo cáo mẫu hardcode.
- Thiếu cả `insight` lẫn `comparison` trả `MISSING_INPUT`; chỉ thiếu một trong hai hoặc thiếu `chart_spec` xử lý theo resolver, giữ limitations và `PARTIAL`; spec sai trả code đúng catalog.
- Hash mismatch, scope violation, lineage/snapshot/semantic mismatch, source pointer sai, value mismatch, binding sai: không ghi artifact report và không tạo delivery thành công.
- `save_report` fail → `REPORT_SAVE_FAILED`; `artifact_put` fail sau save không được trả completed hoặc ref report hợp lệ. Test ghi nhận giới hạn rollback nếu markdown đã lưu.
- Regression cho `REPORT_LLM=off`, metadata StepSpec và `AgentReport@1` parser; không sửa/tắt test cũ để làm pass.

### 9.3 Tích hợp delivery

- Unit nghiệm thu Report Agent khi 9.1–9.2 pass và `report@1` tương thích.
- Chỉ nghiệm thu POC end-to-end Dashboard/PDF/review sau khi Backend/Frontend cung cấp contract/API và integration tests xác nhận cùng report version/content hash/snapshot; trước đó ghi rõ blocker, không gắn trạng thái hoàn tất giả.
- Human review phải xảy ra trước trạng thái hoàn tất theo PRD; Agent không tự approve, publish hay thực hiện recommendation.

## 10. Nguồn tham chiếu và thứ tự ưu tiên

Nếu tài liệu bất nhất, áp dụng theo thứ tự: contract/code hiện hành và các quyết định APPROVED trong `docs/integration/`; PRD và quy định output đã được duyệt; tài liệu mẫu (chỉ tham khảo cách trình bày); tài liệu legacy/draft. Các nguồn đã đối chiếu gồm:

- `docs/PRD_VDAgent.docx` — sáu phần báo cáo, Dashboard/PDF, completeness và human review.
- `docs/VDAgent_Quy_dinh_Output_6_Agent.docx` — metadata/evidence/version/review và nhóm nội dung Report.
- Hai báo cáo mẫu trong `docs/` — mẫu phân tích căn bán chậm và mẫu DQ/audit.
- `docs/integration/CANONICAL_DATA_CONTRACT.md` §9, `AGENT_CONTRACT_MATRIX.md`, `INTEGRATION_MASTER_PLAN.md`, `E2E_TEST_PLAN.md`, `WS7_INDEPENDENT_AUDIT.md` — contract WS6, ranh giới agent và trạng thái tích hợp.
- `docs/agent-a/report/design.md`, `agents/report/vdagent_report/`, `contracts/vdagent_contracts/reports.py`, `catalogs/report.json` — hành vi và schema hiện hành.
- `docs/agent-a/report/task-contract-v0.1.md`, `docs/agent-a/orchestrator/contract-v1.0.md` và API FE v0.3 là legacy/draft khi mô tả phần chưa được implement; không dùng làm runtime contract.
