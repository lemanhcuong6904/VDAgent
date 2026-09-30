# Vinhomes Smart City mock Data Pack

Generator [`generate_vhsc_mock.py`](generate_vhsc_mock.py) dùng seed cố định và kiểm tra [`id_registry.json`](../warehouse/id_registry.json) v3.1.1. Pack có **3.000 căn synthetic**, đúng một dự án `PRJ-VHSC`/`project_key=200`, `unit_key=200001–203000`, `unit_code=SMC-U00001–SMC-U03000` và snapshot 30/06/2026. Generator tạo 16 CSV, `pack_manifest.json` (thứ tự nạp, số dòng, định danh), `row_counts.json`, `expected_scenarios.json`, `negative_controls.json`, `eval_test_cases.json`, `tc_assumptions.json` và [`load_vhsc_mock.sql`](load_vhsc_mock.sql). Chạy từ root repo:

```powershell
python data/generate_vhsc_mock.py
python -m unittest discover -s data/tests -p test_vhsc_pack.py -v
```

`TC-13` và `TC-15` trong `tc_assumptions.json` là **giả định tạm thời**, chưa có Scenario Coverage Matrix/BA xác nhận. TC-13 dùng 1 trong 16 căn của phase pháp lý **hư cấu** `MOCK-LGL-01` (đánh dấu trong `ext_attributes`); TC-15 dùng căn có rơi rụng sâu ở phễu bán. Không suy ra tình trạng giấy phép thật của Vinhomes Smart City từ fixture này. Mã tòa/căn tham khảo trước đây được giữ ở `ext_attributes.tower_unit_label`; `unit_code` theo registry chung.

PostgreSQL 16 dev: container `vdagent-dw-dev`, database `vdagent_dw_dev`, schema `dw`, volume `vdagent_dw_dev_data`, cổng `127.0.0.1:5434`. Password nằm trong `.env` đã bị `.gitignore` loại khỏi Git. Container có `--restart unless-stopped`; volume giữ dữ liệu sau khi restart.

Trên máy có Docker Desktop, chạy [`setup_dev.ps1`](setup_dev.ps1) để tạo hoặc mở lại container/volume và áp dụng migration nếu DB còn trống:

```powershell
./data/setup_dev.ps1
```

```powershell
docker cp 'data/mock/vhsc_20260630/.' 'vdagent-dw-dev:/tmp/vhsc_seed/'
docker cp 'data/load_vhsc_mock.sql' 'vdagent-dw-dev:/tmp/load_vhsc_mock.sql'
docker cp 'data/verify_vhsc_mock.sql' 'vdagent-dw-dev:/tmp/verify_vhsc_mock.sql'
docker exec vdagent-dw-dev psql -U postgres -d vdagent_dw_dev -v ON_ERROR_STOP=1 -f /tmp/load_vhsc_mock.sql
docker exec vdagent-dw-dev psql -U postgres -d vdagent_dw_dev -v ON_ERROR_STOP=1 -f /tmp/verify_vhsc_mock.sql
```

Loader **thay thế dữ liệu trong 16 bảng `dw`**, có guard từ chối database khác `vdagent_dw_dev`. Chỉ dùng với database dev dành riêng cho mock; **không dùng để hợp nhất Central DWH**. Chạy loader lần hai cho cùng số dòng; QA SQL kiểm 16 bảng, công thức, liên kết và 8 nguyên nhân. `data/source_map.md` phân biệt dữ liệu tham khảo công khai và synthetic; không có số liệu CRM/giá giao dịch thực đã được nạp.

Ứng dụng Python hiện dùng SQLite `var/warehouse.db` với 4 bảng bán lẻ demo. `pack_manifest.json` là định dạng xuất để N2 `assemble_dataset(pack_dir)` có thể đọc. Để thử công cụ SQL hiện có trên pack bất động sản, tạo bản chiếu SQLite **riêng** rồi chạy smoke test:

```powershell
python data/build_vhsc_sqlite.py
python -m unittest discover -s data/tests -p test_vhsc_sqlite.py -v
$env:VDAGENT_WAREHOUSE_DB = (Resolve-Path 'var/vhsc_warehouse.db').Path
```

Biến môi trường này chỉ trỏ backend tới file mới trong phiên chạy hiện tại; không ghi đè `var/warehouse.db`. Bản chiếu SQLite phục vụ truy vấn, còn PostgreSQL migration/QA là nơi kiểm contract 16 bảng và constraints. Prompt Data Agent hiện mô tả bán lẻ, nên smoke test trên chưa chứng minh hội thoại agent bất động sản; phần tích hợp chính thức cần owner backend/Data review.

Xem dữ liệu trực tiếp:

```powershell
docker exec -it vdagent-dw-dev psql -U postgres -d vdagent_dw_dev
```

Trong `psql`: `\dt dw.*`, `SELECT count(*) FROM dw.dim_unit_master;`, `SELECT * FROM dw.dm_unit_friction_diagnostics LIMIT 10;`.
