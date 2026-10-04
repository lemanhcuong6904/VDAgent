# Engineering Decisions

Các quyết định kiến trúc còn hiệu lực và các blocker đang mở của VDaAgent (người đọc: engineer, Integration Owner,
team DATA). Trích từ `docs/archive/integration-2026-09/INTEGRATION_MASTER_PLAN.md` (D1–D10 được Integration Owner duyệt ngày
2026-09-30; tiến độ WS1–WS7 nằm trong tài liệu đó và không lặp lại ở đây) và trạng thái hiện tại trong
[AGENTS.md](../../AGENTS.md). Kiến trúc: [system.md](system.md).

## Accepted Decisions

| ID | Decision | Rationale | Status |
|---|---|---|---|
| D1 | Dữ liệu chuẩn là kho bất động sản của Backend, chỉ đọc qua Data (`re_run_query`, có giới hạn phạm vi). | Một nguồn sự thật có quản trị; Insight/Compare không tự đọc pack CSV riêng. | **APPROVED**; production là AWS RDS `cdw` (view `re` trên `gold`, `SNAP-20260630-01`, `3.1.0`) từ 2026-10-01; kho giả SQLite chỉ cho test/offline khi chỉ định rõ |
| D2 | Khóa chuẩn là khóa TEXT của DW; model dòng của Insight dùng khóa `str` và mở rộng enum (`INTERNAL_COURT`, `LOCKED`). | Insight trước đó dùng khóa `int` và enum hẹp, không khớp DW. | **APPROVED** |
| D3 | Insight có cấu hình semantic `sc-1` riêng (không ánh xạ sang `3.1.0`). | DW giả dùng `sc-1`; Insight cần đọc đúng phiên bản của dữ liệu nó nhận. | **APPROVED**; áp dụng cho kho giả `sc-1`; production chạy semantic `3.1.0` |
| D4 | Data phục vụ `StepSpec` tất định (`fetch_units`, `aggregate_metrics`); SQL do LLM viết chỉ dành cho câu tự do. | Kết quả lặp lại được, không phụ thuộc LLM trên luồng chính. | **APPROVED**, IMPLEMENTED |
| D5 | Orchestrator là bộ thực thi DAG bằng code; LLM chỉ phân loại ý định và đề xuất plan (được kiểm tra bằng code). | Luồng điều khiển kiểm chứng được; LLM không chèn được spec, snapshot hay id. | **APPROVED**, IMPLEMENTED |
| D6 | Chart là plugin chính thức của Backend; dữ liệu demo/tổng hợp không bao giờ vào luồng production. | Biểu đồ phải lấy từ artifact thật. | **APPROVED**, IMPLEMENTED (demo chỉ khi `CHART_DEMO=on`) |
| D7 | Report dùng artifact của Chart (`save_report` nhúng `chart_spec`); workflow bán lẻ và `create_chart` được giữ. | Báo cáo trích dẫn đúng biểu đồ đã kiểm chứng. | **APPROVED**, IMPLEMENTED |
| D8 | Không bao giờ tự điền giá trị thiếu; ghi `null` kèm mã hạn chế (`METRIC_UNAVAILABLE`, `WINDOW_INCOMPLETE`). | Không bịa số. | **APPROVED**, IMPLEMENTED |
| D9 | `net_area_m2` là diện tích chuẩn để chọn peer; không fallback sang `area_m2`. | Một định nghĩa diện tích cho mọi agent. | **APPROVED**, IMPLEMENTED (`peer_rules.peer_area`) |
| D10 | Fixture DW của Backend dùng cho test tích hợp; fixture cũ của từng agent giữ cho test regression độc lập. | Test tích hợp chạy trên cùng một nguồn; test cũ không bị phá. | **APPROVED** |

## Open Blockers

| ID | Issue | Impact | Owner / next action (theo tài liệu nguồn) |
|---|---|---|---|
| D2b | Ánh xạ `segment` của dự án (DW `HIGH_END`/`MID_END` ↔ enum Insight `AFFORDABLE/MID/MID_HIGH/LUXURY`) chưa định nghĩa. | Trường `segment` của Insight. | DATA owner; không được tự đoán. |
| B-2 | `min_group_size` còn PENDING trong `sc-1`, còn Compare đọc `min_peer_count` không tồn tại; Compare chạy với mặc định 5 và gắn `BLOCKED:B-2_min_peer_count` vào artifact. | Ngưỡng số peer tối thiểu. | Cần duyệt giá trị/khóa cấu hình. |
| B-3 | `net_area_m2` của kho giả là dữ liệu tổng hợp (`area_m2 × 0.92`), ý nghĩa nghiệp vụ chưa xác nhận. | Ký duyệt kết quả peer; giới hạn `SYNTHETIC_SOURCE`. | DATA owner xác nhận. |
| B-11 | Không có luật chọn peer được duyệt nào tái tạo đúng 7 peer golden; Compare chọn 5. | Test chấp nhận tập peer và biểu đồ 7 peer (đang skip). | Integration Owner / DATA owner. |
| B-12 | Mã hành động / mẫu câu và các ngưỡng riêng của Insight chưa có nguồn `sc-1` được duyệt. | Câu chữ và khuyến nghị của Insight trên `sc-1`. | Cần nguồn cấu hình được duyệt. |
| F-05 | Chưa có xác thực: `X-User-Id` chỉ dùng cho dev. | Chưa sẵn sàng production. | Quyết định AUTH-1…AUTH-5 trong [auth-design.md](../security/auth-design.md). |

Các blocker khác trong kế hoạch tích hợp (B-1, B-4 … B-10) đã được giải quyết hoặc thay bằng quyết định ở trên; chi tiết
lịch sử nằm trong `docs/archive/integration-2026-09/INTEGRATION_MASTER_PLAN.md`.
