# Data assets

Thư mục `data/` chỉ còn **ba seeder** của ứng dụng (cũng là các file `data/` duy nhất được copy vào image):

| File | Tạo gì | Dùng ở đâu |
|---|---|---|
| `seed_warehouse.py` | kho bán lẻ demo `var/warehouse.db` (sinh với `random.Random(42)`) | `make reset-db`, `docker/seed-if-missing.sh` |
| `seed_users.py` | người dùng demo + scope (`VDAGENT_SCOPE_PROFILE=demo\|real`) | `make reset-db`, `docker/seed-if-missing.sh` |
| `seed_re_warehouse.py` | kho bất động sản **giả** SQLite (`SNAP-2026-09-28`, `sc-1`, căn `A12-08`) cho test/offline | `make mock-up`, test, acceptance; chỉ khi được chọn rõ ràng, không bao giờ ghi vào DSN PostgreSQL |

## Kho dữ liệu thật

Kho chuẩn của production là **AWS RDS `cdw`** (schema `gold`, Backend đọc qua view `re`), snapshot
`SNAP-20260630-01`, semantic `3.1.0`; bản DR là
[`warehouse/backup/cdw_gold_snapshot_20260630.dump`](../warehouse/backup/README.md). Dải khoá các dự án theo
[`warehouse/id_registry.json`](../warehouse/id_registry.json), DDL 16 bảng ở
[`warehouse/schema_final_16_tables.sql`](../warehouse/schema_final_16_tables.sql), quy tắc snapshot ở
[`warehouse/SNAPSHOT_RULES.md`](../warehouse/SNAPSHOT_RULES.md). Thay đổi dữ liệu kho do team DATA làm trên kho chuẩn,
rồi làm mới dump DR; repo ứng dụng **không còn lưu CSV dataset của warehouse**.

| `project_key` | `project_id` | Dự án | Owner (task) |
|---|---|---|---|
| 100 | `PRJ-VHOP` | Vinhomes Ocean Park | Lưu Xuân Dũng (N7) |
| 200 | `PRJ-VHSC` | Vinhomes Smart City | Nguyễn Quang Huy (N4) |
| 300 | `PRJ-VGP` | Vinhomes Grand Park | Hà Duy Anh (N3) |
| 400 | `PRJ-MAS-CP` | Masteri Centre Point | Nguyễn Tuấn Anh (N6) |
| 500 | `PRJ-RISK-PHU-MY-BRVT` | Dự án Rủi ro Pháp lý – Phú Mỹ (BRVT) | Nguyễn Mai Huy (N5) |

## Raw pack và pipeline cũ (đã gỡ khỏi repo)

Pipeline CSV dựng ra kho (retire ở Phase 2) và các raw pack của 5 dự án, generator, dbt project, PostgreSQL dev cục
bộ (`setup_dev.ps1`, loader/QA SQL, `migrations/`) đã được gỡ khỏi cây làm việc ở Phase 3 (2026-10-04). Không file nào
trong số đó là dependency runtime. Danh sách từng file (đường dẫn, kích thước, số dòng, sha256, git blob, phân loại,
generator/seed, snapshot nguồn) và lệnh khôi phục nằm ở
[`docs/data-archive/phase3-manifest.json`](../docs/data-archive/phase3-manifest.json); mọi file có nguyên văn trong
commit `aed2917` (có trên `origin/main`), ví dụ:

```bash
git checkout aed2917 -- data/VGP           # khôi phục cả một pack
git show aed2917:<đường dẫn> > <đường dẫn>  # một file; kiểm sha256 theo manifest
```
