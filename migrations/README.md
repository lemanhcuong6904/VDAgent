# VDAgent warehouse migration

`001_create_dw_v3_1_0.sql` tạo schema `dw` và đủ 16 bảng theo [data contract](../docs/data-warehouse-data-contract-v3.1.0.md). Chạy bằng PostgreSQL 16+ trên **database trống**; migration không được thiết kế để chạy hai lần trên cùng database.

```powershell
createdb -U postgres vdagent_dw_test
psql -U postgres -d vdagent_dw_test -v ON_ERROR_STOP=1 -f migrations/001_create_dw_v3_1_0.sql
psql -U postgres -d vdagent_dw_test -v ON_ERROR_STOP=1 -f migrations/verify_dw_v3_1_0.sql
```

Để kiểm tra tính tái lập, tạo **database trống thứ hai** và chạy lại đúng hai lệnh `psql` trên với tên database mới. `verify_dw_v3_1_0.sql` kiểm tra số bảng, cột, PK/FK/UK/CHECK/index và thử các giá trị sai; dữ liệu thử được `ROLLBACK`.

Các quy tắc cần dữ liệu từ bảng khác hoặc từ nhiều dòng, như đơn giá/m² theo `dim_unit_master.net_area_m2`, tổng `attribution_score = 1.000` và `is_overdue_flag` theo `semantic_config`, thuộc bước kiểm thử data quality khi nạp mock data. Migration không tạo FK sang backend database.
