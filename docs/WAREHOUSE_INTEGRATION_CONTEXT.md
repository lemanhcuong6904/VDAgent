# Context: Tích hợp Central Data Warehouse

**Cập nhật:** 2026-09-30  
**Nhánh làm việc:** `integrate/DATA-rollout`  
**Mục tiêu:** hợp nhất dữ liệu mock của project 100, 200, 300, 400 và 500 thành một warehouse canonical dưới `warehouse/`.

## Phạm vi và nguồn dữ liệu

| Project | Tên | Nguồn | Trạng thái warehouse |
|---:|---|---|---|
| 100 | Vinhomes Ocean Park | `origin/DATA-XuanDung` | Đã tích hợp trước đó |
| 200 | Vinhomes Smart City | `origin/DATA-NguyenQuangHuy` | Đã tích hợp trước đó |
| 300 | Vinhomes Grand Park | `origin/DATA-HaDuyAnh` | Đã tích hợp và đã pass quality gate |
| 400 | Masteri Centre Point | `backup/DATA-NguyenTuanAnh-local-save` | Đã chuẩn hóa trong workspace, chưa commit |
| 500 | Phú Mỹ / Risk project | `origin/DATA-NguyenMaiHuy` | Đã chuẩn hóa trong workspace, chưa commit |

Không merge nguyên nhánh 400/500 vào branch tích hợp vì chúng tách từ nền code cũ và sẽ kéo theo thay đổi backend không liên quan. Thay vào đó, chỉ các CSV mock thuộc phạm vi warehouse được nhập, chuẩn hóa và có thể truy xuất nguồn.

## Những phần đã hoàn thành

1. Đã xác định nhánh tích hợp hiện tại là `integrate/DATA-rollout`; không có merge conflict đang mở.
2. Đã commit source pack project 300:
   - `8ef46c2 feat(data): add Vinhomes Grand Park source pack`
3. Đã commit canonical pack project 300 và adapter ban đầu:
   - `1a1db03 feat(warehouse): register Vinhomes Grand Park project 300 pack`
4. Đã sửa trong workspace quy tắc funnel cho project 300: khi một event có cancellation lớn hơn reservation, reservation được nâng tối thiểu bằng cancellation để giữ lại số cancellation và thỏa contract.
5. Đã tạo tài liệu quy tắc Git/warehouse:
   - `0724028 docs(git): add warehouse integration guide`
   - File: `docs/GIT_WAREHOUSE_INTEGRATION_RULES.md`
6. Đã đưa raw CSV Masteri ra khỏi thư mục output sang `data/masteri_cp/csv/`. Nguồn này gồm đúng 13 CSV fixture cần để tái tạo pack 400.
7. Đã lấy raw CSV project 500 về `data/risk_project_mock/csv/`.
8. Đã mở rộng `warehouse/organize_pack.py` để chuẩn hóa project 400 và 500.
9. Đã chạy thành công:

   ```powershell
   python warehouse/organize_pack.py
   python warehouse/verify_warehouse.py
   ```

   Quality gate pass cho đủ 5 project.

## Chuẩn hóa/re-key đã áp dụng

Các nhánh nguồn 400 và 500 sử dụng key band cũ. Adapter chuyển chúng về band trong `warehouse/id_registry.json` và cập nhật cả khóa ngoại trong các CSV canonical.

| Project | Trường | Nguồn | Canonical |
|---:|---|---:|---:|
| 400 | `project_id` | `MAS-U` | `PRJ-MAS-CP` |
| 400 | `zone_key` | `4001–4010` | `401–410` |
| 400 | `channel_key` | `40001–40006` | `4001–4006` |
| 400 | `infra_key` | `40001–40004` | `4101–4104` |
| 500 | `zone_key` | `2201–2202` | `501–502` |
| 500 | `channel_key` | `3201–3204` | `5001–5004` |
| 500 | `infra_key` | `4201` | `5101` |

## Trạng thái hoàn thành

Tất cả các task tích hợp và commit dữ liệu còn lại đã hoàn tất:

1. `feat(data): add project 400 mock source pack` (`data/masteri_cp/csv/`)
2. `feat(data): add project 500 mock source pack` (`data/risk_project_mock/csv/`)
3. `feat(warehouse): integrate project 400 canonical pack` (`warehouse/project_400/`)
4. `feat(warehouse): integrate project 500 canonical pack` (`warehouse/project_500/`)
5. `fix(warehouse): normalize project 300 funnel data and adapter` (`warehouse/organize_pack.py`, `warehouse/project_300/fact_sales_funnel_daily.csv`)

## Kiểm chứng sau commit

- `python warehouse/organize_pack.py`: Thành công.
- `python warehouse/verify_warehouse.py`: Tất cả 5 project (100, 200, 300, 400, 500) đã PASS toàn bộ kiểm tra contract & logic.

