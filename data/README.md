# Vinhomes Smart City mock Data Pack

Generator [`generate_vhsc_mock.py`](generate_vhsc_mock.py) dùng seed cố định, tạo 16 CSV, `row_counts.json`, `expected_scenarios.json`, `negative_controls.json`, `eval_test_cases.json` và [`load_vhsc_mock.sql`](load_vhsc_mock.sql). Chạy từ root repo:

```powershell
python data/generate_vhsc_mock.py
```

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

Loader **thay thế dữ liệu trong 16 bảng `dw`**, có guard từ chối database khác `vdagent_dw_dev`. Chỉ dùng với database dev dành riêng cho mock. Chạy loader lần hai cho cùng số dòng; QA SQL kiểm 16 bảng, công thức, liên kết và 8 kịch bản. `data/source_map.md` phân biệt dữ liệu tham khảo công khai và synthetic; không có số liệu CRM/giá giao dịch thực đã được nạp.

Xem dữ liệu trực tiếp:

```powershell
docker exec -it vdagent-dw-dev psql -U postgres -d vdagent_dw_dev
```

Trong `psql`: `\dt dw.*`, `SELECT count(*) FROM dw.dim_unit_master;`, `SELECT * FROM dw.dm_unit_friction_diagnostics LIMIT 10;`.
