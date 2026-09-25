# QA result — Vinhomes Smart City mock Data Pack

**Ngày:** 25/09/2026. **Môi trường:** PostgreSQL 16 Alpine trong `vdagent-dw-dev`, database `vdagent_dw_dev`, Docker volume `vdagent_dw_dev_data`.

| Kiểm tra | Kết quả |
| --- | --- |
| Migration | 16 bảng, 178 cột; 16 PK, 21 FK, 9 UK, 94 CHECK, 41 index. Chạy đạt trên hai database trống ở bước DDL. |
| Nạp dữ liệu | 16/16 bảng, 8.456 dòng; số dòng từng bảng ở `mock/vhsc_20260630/row_counts.json`. |
| Quy mô mục tiêu | 1.200 căn thuộc `PRJ-VHSC-HN`; 816 SOLD, 84 BOOKED, 300 AVAILABLE; 120 căn mục tiêu AVAILABLE có DOM >90. |
| Scenario | 136 chẩn đoán, 193 dòng bridge; 8/8 mã nguyên nhân chính có 16–18 ca/mã. |
| Dữ liệu | Công thức giá/m², DOM, trạng thái, performance kênh, source/lineage và tổng attribution được SQL QA đối chiếu. |
| Đối chứng | SOLD, BOOKED, AVAILABLE DOM=90 không được chẩn đoán; AVAILABLE DOM=91 có chẩn đoán. |
| Eval | 11 câu `expected_sql_query` trả về đúng `ground_truth_causes` trên PostgreSQL dev. |
| Tái lập | Generator tạo file giống hệt từng byte khi chạy lại; loader nạp lần hai đạt cùng QA; restart container vẫn giữ đủ dữ liệu. |

**Lệnh xác minh:** `docker exec vdagent-dw-dev psql -U postgres -d vdagent_dw_dev -v ON_ERROR_STOP=1 -f /tmp/verify_vhsc_mock.sql` (sau khi copy SQL từ repo như trong [`README.md`](README.md)). Script kết thúc bằng `ROLLBACK` và không thay đổi dữ liệu.

**Giới hạn:** Toàn bộ dữ liệu nghiệp vụ là synthetic; các nguồn công khai chỉ được dùng làm tham khảo về tòa và loại căn. `PRJ-VHSC-LEGAL-MOCK` là fixture hư cấu cho ca pháp lý. Chưa có CRM hoặc giao dịch thứ cấp xác thực để đối chiếu thị trường thực.
