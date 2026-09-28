# VHOP Data Pack

Bộ dữ liệu warehouse phân tích cho **Vinhomes Ocean Park (VHOP)** — dùng làm nguồn
dữ liệu để các agent (`data`, `compare`, `insight`) chẩn đoán thanh khoản bất động
sản (đơn vị tồn kho DOM > 90 ngày) theo ma trận **8 nguyên nhân**.

Dữ liệu là **tổng hợp (synthetic)**: các mốc như tên khu, diện tích, giá, tỉ lệ
thang máy, hạ tầng được neo theo số liệu VHOP có thật nhưng dữ liệu unit/giao dịch
là mô phỏng — **không có dữ liệu khách hàng/giao dịch thật**.

Nguồn: chuyển giao từ repo cá nhân `vdagent-xdg` (bộ sinh Python, deterministic
seed `20260630`). Bộ sinh **chưa** được migrate sang đây; cụm này là *deliverable đã
sinh sẵn*, có thể tái tạo lại từ seed ở repo gốc.

## Nội dung

| Đường dẫn | Mô tả |
|---|---|
| `ddl/` | 7 file DDL PostgreSQL (`00`→`06`): 16 bảng Data Warehouse + 3 bảng CRM + `users`. PK là INTEGER/BIGINT cố định (không SERIAL) để đảm bảo determinism. |
| `export/` | 20 file CSV + `load.sql` — bản dump portable, self-contained (meta + dims + facts + CRM + 2 mart chẩn đoán). Nạp thẳng vào Postgres/Supabase. |
| `gold_standard_sql/` | 7 SQL chuẩn tính lại từng metric từ facts gốc + README. Dùng làm **oracle kiểm chứng** kết quả của agent/mart, và làm query mẫu. |
| `semantic_config.json` | Single-source-of-truth cho toàn bộ ngưỡng/tham số của 8 nguyên nhân. Cần để hiểu vì sao mart ra con số đó. |
| `scenario_coverage.md` | Bằng chứng phủ đủ 8/8 nguyên nhân trên dataset. |

Quy mô dataset: **3.000 units**, **1.139 diagnostics** (đơn vị AVAILABLE & DOM > 90).

## Dựng warehouse từ cụm này

Yêu cầu: một PostgreSQL trống (dùng `psql`).

```sh
# 1. Áp schema theo đúng thứ tự
for f in ddl/00_extensions.sql ddl/01_meta.sql ddl/02_dimensions.sql \
         ddl/03_facts.sql ddl/04_marts.sql ddl/05_crm.sql ddl/06_indexes.sql; do
  psql "$DATABASE_URL" -f "$f"
done

# 2. Nạp dữ liệu (chạy TỪ trong thư mục export/ vì load.sql dùng đường dẫn tương đối)
cd export && psql "$DATABASE_URL" -f load.sql
```

## Kết nối với nền tảng

Nền tảng đọc warehouse qua adapter, không đọc file trực tiếp. Sau khi dựng Postgres
ở trên, trỏ `PostgresWarehouseAdapter` (`src/providers/warehouse/postgres.ts`) vào DB
đó qua config trong `.env`:

- `WAREHOUSE_POSTGRES_ENABLED=true`
- `DATABASE_URL` (hoặc biến kết nối warehouse tương ứng) → DB vừa nạp.

> Việc viết/điều chỉnh adapter và wiring vào registry thuộc phần code (Phương án B),
> **chưa làm ở lần chuyển giao này**. Cụm này mới là dữ liệu + DDL + SQL kiểm chứng.

## Lưu ý ownership / quy trình

- Thuộc domain **DATA** (`PLAN.md §11`, `docs/folder-ownership.md`).
- Dữ liệu tổng hợp — không vi phạm quy tắc "không commit dữ liệu thật" ở `GIT_RULE.md §9`.
- Toàn bộ `export/` là artifact **tái tạo được** từ seed cố định ở repo gốc.
