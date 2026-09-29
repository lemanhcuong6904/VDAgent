# QA — Vinhomes Smart City mock Data Pack

**Ngày kiểm tra:** 29/09/2026. **Nguồn dữ liệu:** synthetic, snapshot 30/06/2026. **PostgreSQL dev:** container `vdagent-dw-dev`, database `vdagent_dw_dev`, schema `dw`; không dùng database chia sẻ.

| Kiểm tra | Kết quả |
| --- | --- |
| Migration trên hai database trống | PASS trên `vdagent_dw_n4_repro_a` và `vdagent_dw_n4_repro_b`: 16 bảng, 178 cột (150 NOT NULL), 16 PK, 21 FK, 9 UK, 94 CHECK, 41 index; negative tests trong `migrations/verify_dw_v3_1_0.sql` đạt. |
| Nạp dữ liệu | PASS 16/16 bảng, **20.307 dòng**; `dim_unit_master=3.000`, `fact_unit_inventory_snapshot=3.000`, `fact_sales_funnel_daily=12.000`. Xem `mock/vhsc_20260630/row_counts.json`. |
| Registry/snapshot | Một `PRJ-VHSC`/project key 200; unit key 200001–203000, unit code SMC-U00001–SMC-U03000; zone/channel/infra đúng dải N1; snapshot `SNAP-20260630-01`. |
| Trạng thái | 2.040 SOLD, 210 BOOKED, 750 AVAILABLE; 316 căn AVAILABLE có DOM >90 và 316 chẩn đoán. |
| Scenario | 8/8 nguyên nhân chính, mỗi nguyên nhân có 16–43 ca; 449 dòng bridge, tổng attribution 1.000/chẩn đoán. Kiểm giá/m², DOM, trạng thái, kênh và bằng chứng kịch bản bằng SQL. |
| Đối chứng và eval | SOLD, BOOKED, AVAILABLE DOM=90 không bị chẩn đoán; DOM=91 có chẩn đoán. **11/11** câu `expected_sql_query` khớp `ground_truth_causes` trên PostgreSQL dev. |
| Tái lập | 22 file CSV/JSON giống hệt từng byte khi chạy generator lại. Loader nạp lần hai và SQL QA tiếp tục PASS. |
| Backend SQLite | Bản chiếu `var/vhsc_warehouse.db` đọc được bằng chính hàm MCP SQL của backend: 16 bảng, 3.000 căn, 16 ca legal mock. Đây là smoke test công cụ truy vấn, chưa phải kiểm thử hội thoại agent. |

**Lệnh kiểm tra:** `python -m unittest discover -s data/tests -p 'test_vhsc*.py' -v`; `python data/verify_vhsc_eval.py`; `docker exec vdagent-dw-dev psql -U postgres -d vdagent_dw_dev -v ON_ERROR_STOP=1 -f /tmp/verify_vhsc_mock.sql`. SQL QA kết thúc bằng `ROLLBACK`.

**Giới hạn:** TC-13 và TC-15 được cài theo giả định tạm trong `mock/vhsc_20260630/tc_assumptions.json` vì chưa có Scenario Coverage Matrix/BA xác nhận. 16 căn ở phase `MOCK-LGL-01` là fixture pháp lý **hư cấu**, không phản ánh giấy phép thật của Vinhomes Smart City. Nguồn công khai chỉ tham khảo tên tòa và loại căn; không có CRM, giá giao dịch hay tình trạng pháp lý xác thực. Backend hiện còn prompt bán lẻ và kho demo mặc định; cần quyết định tích hợp chính thức với owner backend/Data.
