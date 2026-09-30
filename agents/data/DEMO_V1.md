# Thử Data agent bằng tin nhắn theo contract v1.0

Data agent nhận trực tiếp tin `DISPATCH` của contract Orchestrator ↔ Agent v1.0. Dán một khối JSON dưới đây vào khung chat của agent **data** (chọn người dùng **Alice**, id `u_000000000001`, phạm vi dự án 100 và 400) rồi gửi. Data kể lại công việc, cuối cùng trả đúng một khối ```` ```json ```` là tin `REPORT` (hoặc `COMMAND_ACK` nếu tin sai).

Lưu ý khi thử:

- `idempotency_key` phải là `plan_id:step_id`. Cùng khóa, cùng nội dung: Data trả lại kết quả cũ, không đọc lại. Cùng khóa, khác nội dung: lỗi `ID_CONFLICT`. Mỗi ví dụ dưới đây dùng một `step_id` riêng.
- `snapshot_id: null`: Data tự khóa kỳ chốt đã duyệt mới nhất và đọc phiên bản cấu hình từ kỳ đó.
- Hỏi lại (QUESTION): trả lời bằng tin `ANSWER` (ví dụ 7).
- Chạy trên DW thật cần `DATA_DW_PROFILE=real` trong `agents/data/.env`.

Khung chung của mọi ví dụ (chỉ `step_id`, `idempotency_key`, `original_question`, `operation` và `spec` đổi):

```json
{"contract_version":"1.0.0","message_id":"m-1","message_type":"DISPATCH","sent_at":"2026-09-30T10:00:00Z","run_id":"run-demo-1","plan_id":"pl-demo","step_id":"B1","agent":"DATA","idempotency_key":"pl-demo:B1","body":{"operation":"fetch_units","catalog_version":"1.0.0","plan_version":1,"objective":"Lấy căn","original_question":"Vì sao căn OCP-U00001 bán chậm?","task_kinds":["EXPLAIN"],"locale":"vi-VN","user_context":{"user_id":"u_000000000001","role":"SALES_OPS","authorized_scope":{"project_ids":[],"zone_ids":[]}},"conversation_id":null,"parent_run_id":null,"snapshot_id":null,"deadline_s":90,"wait_list":[],"forward_to":[],"spec":{"entities":[{"mention":"OCP-U00001","kind_hint":"UNIT"}]}}}
```

## 1. Một căn, gõ tự do (chuẩn hóa mã căn)

Đổi `step_id` thành `B2`, `idempotency_key` thành `pl-demo:B2`, `spec` thành:

```json
{"entities":[{"mention":"ocp u00001","kind_hint":"UNKNOWN"}]}
```

Kỳ vọng: DONE, gói `unit_set`, `ext.entities_resolved[0].method = "normalized"`.

## 2. Một phân khu theo tên (kèm từ chỉ cấp)

`B3`, `question`: "Tình hình phân khu The Sapphire 1?", `spec`:

```json
{"entities":[{"mention":"phân khu The Sapphire 1","kind_hint":"ZONE"}],"attributes":["floor_band","balcony_orientation","view_type"]}
```

Kỳ vọng: DONE, 400 căn của phân khu đó.

## 3. Tên mơ hồ: Data hỏi, không đoán

`B4`, `question`: "Tại sao phân khu Riviera bán chậm?", `spec`:

```json
{"entities":[{"mention":"Riviera","kind_hint":"ZONE"}]}
```

Kỳ vọng: REPORT `QUESTION` với 5 phân khu (Tòa A đến E), không gói nào được lưu. Trả lời bằng tin `ANSWER` (ví dụ 7).

## 4. Toàn phạm vi, căn bán chậm

`B5`, `question`: "Liệt kê các căn bán chậm", `spec`:

```json
{"scope_all":true,"filters":["slow_moving"]}
```

Kỳ vọng: DONE, 2011 căn (AVAILABLE và số ngày tồn lớn hơn ngưỡng 90 đã duyệt trong kho).

## 5. Tính chỉ số theo nhóm

`B6`, `operation`: `aggregate_metrics`, `question`: "Tỷ lệ bán chậm theo phân khu?", `spec`:

```json
{"scope_all":true,"metrics":["unit_count","slow_moving_count","slow_moving_rate","absorption_rate","avg_dom_unsold"],"group_by":["zone"]}
```

Kỳ vọng: DONE, gói `metric_table`; `absorption_rate` kèm cảnh báo `PROVISIONAL_DEFINITION`.

## 6. Nhóm tương đồng và bối cảnh của một căn

`B7`, `operation`: `fetch_peer_candidates`, `question`: "So sánh căn OCP-U00001 với các căn tương đồng", `spec`:

```json
{"entities":[{"mention":"OCP-U00001","kind_hint":"UNIT"}]}
```

`B8`, `operation`: `fetch_unit_context`, `spec`:

```json
{"entities":[{"mention":"OCP-U00001","kind_hint":"UNIT"}],"context_groups":["price","funnel","secondary","macro","infra"]}
```

## 7. Trả lời câu hỏi (ANSWER)

Sau ví dụ 3, sao chép `question_id` và một `option_id` từ tin QUESTION:

```json
{"contract_version":"1.0.0","message_id":"m-ans-1","message_type":"ANSWER","sent_at":"2026-09-30T10:01:00Z","run_id":"run-demo-1","plan_id":"pl-demo","step_id":"B4","agent":"DATA","idempotency_key":"pl-demo:B4","body":{"question_id":"<question_id>","selected_option_ids":["opt-1"],"answered_by":"u_000000000001","answered_at":"2026-09-30T10:01:00Z"}}
```

Kỳ vọng: DONE, `ext.entities_resolved[0].method = "saved_choice"`. Lựa chọn được nhớ cho các bước sau của cùng `run_id`.

## 8. Những tin sai, để xem Data từ chối đúng cách

| Thử | Kỳ vọng |
|---|---|
| Bỏ trường `objective` | `COMMAND_ACK` `REJECTED` `MALFORMED_MESSAGE` |
| `contract_version` = `2.0.0` | `REJECTED` `UNSUPPORTED_CONTRACT_VERSION` |
| `agent` = `INSIGHT` | `REJECTED` `WRONG_AGENT` |
| `spec` = `{"scope_all":true,"filters":["cheap"]}` | `REPORT` `ERROR` `SPEC_INVALID` |
| `mention` = `căn của dự án khác` hoặc mã không có | `ERROR` `OUT_OF_SCOPE`, hoặc `QUESTION` gợi ý mã gần nhất trong phạm vi |
| `snapshot_id` = `SNAP-NOPE` | `ERROR` `DQ_BLOCKING` |
| `user_id` khác người đang chọn | `ERROR` `OUT_OF_SCOPE` |
