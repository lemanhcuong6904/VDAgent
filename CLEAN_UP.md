# Đề xuất dọn thư mục làm việc — 29/09/2026

## Căn cứ kiểm tra

- Nhánh đang làm: `DATA-NguyenQuangHuy` (`c6114bc`). Đã đối chiếu các đầu nhánh trên `origin` ngày 29/09/2026 và cây file của từng nhánh; đây là nhận xét về **trạng thái hiện tại**, không chỉ lịch sử commit.
- `origin/main` (`aad64b7`) chạy ứng dụng Python, SQLite và React. `origin/DATA` (`a8bca11`) chỉ khác `main` ở hai file: `warehouse/id_registry.json` v3.1.1 và `warehouse/SNAPSHOT_RULES.md`.
- Sau lần khôi phục file trên máy, 469 file cũ đang có mặt nhưng **chưa được Git theo dõi**. Vì vậy file nhìn thấy trên máy không đồng nghĩa với file đã có trên nhánh remote. Không dùng `git add .` cho toàn bộ thư mục.

## Nhóm Data đã làm tới đâu

| Hạng mục | Kết quả kiểm tra ngày 29/09 | Việc còn thiếu |
| --- | --- | --- |
| Quy ước tích hợp 5 dự án | Nhánh `DATA` đã công bố dải khóa riêng, mã dự án, owner và snapshot chung `SNAP-20260630-01` cho Ocean Park, Smart City, Grand Park, Masteri và dự án rủi ro. | Áp dụng registry v3.1.1 vào từng pack, kiểm tra khóa trùng và ràng buộc giữa các pack. |
| Ocean Park | Pack 16 bảng có trong lịch sử commit `adf2d05` ngày 28/09, nhưng commit đồng bộ ứng dụng `6af70b5` đã bỏ `warehouse/vhop` khỏi cây file hiện tại của `DATA` và `main`. | Khôi phục vào nhánh làm việc phù hợp, đổi khóa theo registry, rồi tích hợp lại. |
| Smart City — Nguyễn Quang Huy | Thư mục `data/mock/vhsc_20260630/` trên máy có 16 CSV; báo cáo QA cũ ghi 8.456 dòng, trong đó `dim_unit_master` có 1.216 dòng (1.200 căn Smart City và 16 căn fixture pháp lý). Có generator, migration PostgreSQL, loader, kiểm tra SQL và kịch bản. | Hiện toàn bộ pack là file chưa được Git theo dõi trên nhánh này và chưa có trên `DATA`; phải đồng bộ định danh, chạy lại QA rồi đưa lên bằng PR riêng. |
| Grand Park, Masteri | Các commit làm pack còn trong lịch sử nhánh cá nhân, nhưng cây file hiện tại của `DATA-HaDuyAnh` và `DATA-NguyenTuanAnh` không còn pack sau commit đồng bộ ứng dụng. | Chủ pack khôi phục từ lịch sử, đối chiếu registry và mở PR. |
| Dự án rủi ro | `DATA-NguyenMaiHuy` (`b73e437`) còn pack 16 bảng, 3.000 căn và tài liệu QA trong cây file hiện tại. | Kiểm tra lại với registry/snapshot chung và đưa vào `DATA` sau review; pack chưa nằm trên `DATA`. |
| Ứng dụng đang chạy | `backend/config.yaml` dùng `var/warehouse.db`; `data/seed_warehouse.py` tạo warehouse demo bán lẻ SQLite với 4 bảng (`dim_date`, `dim_product`, `dim_store`, `fact_sales`). | Chưa có đường nạp và truy vấn 16 bảng bất động sản qua ứng dụng hiện tại. QA PostgreSQL cũ không chứng minh ứng dụng SQLite hiện tại đã dùng được pack. |

**Đánh giá:** Nhóm đã có quy ước tích hợp và đã tạo được dữ liệu dự án trên các nhánh/lịch sử riêng. Chưa có bộ 5 dự án đã hợp nhất, cùng khóa và snapshot, được nạp vào warehouse mà ứng dụng hiện tại sử dụng.

## Đề xuất với file trong thư mục hiện tại

| Quyết định | File/thư mục | Lý do và bước tiếp theo |
| --- | --- | --- |
| **Giữ, ưu tiên đưa vào PR Smart City** | `data/generate_vhsc_mock.py`, `data/mock/vhsc_20260630/` (16 CSV và các JSON đánh giá), `data/README.md`, `data/source_map.md`, `data/scenario_coverage.md`, `data/qa_results.md` | Đây là sản phẩm Data Pack và bằng chứng nguồn/QA; không xóa cùng nền tảng cũ. Xác minh lại kết quả sau khi sửa khóa. |
| **Giữ làm công cụ PostgreSQL riêng** | `migrations/001_create_dw_v3_1_0.sql`, `migrations/verify_dw_v3_1_0.sql`, `migrations/README.md`, `data/load_vhsc_mock.sql`, `data/verify_vhsc_mock.sql`, `data/setup_dev.ps1` | Có ích để tái lập pack 16 bảng. Loader đang `TRUNCATE` cả 16 bảng, chỉ có guard cho database dev `vdagent_dw_dev`; không dùng trực tiếp trên warehouse chung. Cần quyết định adapter/migration cho ứng dụng SQLite hiện tại. |
| **Giữ làm nguồn đối chiếu** | `docs/data-warehouse-data-contract-v3.1.0.md`, `docs/Data Warehouse Schema (Final).docx`, `docs/Backend Application Database & DDL (Final).docx`, `docs/VDaAgent_Feasibility_Proposal.docx`, `docs/erd-diagram-warehouse.png`, `docs/erd-diagram-database.png` | Là tài liệu gốc để rà soát 16 schema và nghiệp vụ. Khi xung đột khóa/snapshot, áp dụng registry v3.1.1 và quy tắc trên nhánh `DATA`; ghi rõ khác biệt trước PR. |
| **Giữ nguyên nền tảng mới đang được theo dõi** | `backend/`, `agents/<tên-agent>/`, `sdk/vdagent_sdk/`, `frontend/` hiện có trên `HEAD`, `data/seed_users.py`, `data/seed_warehouse.py`, `pyproject.toml`, `uv.lock`, `Dockerfile.python`, `docker-compose.yml`, `README.md`, `docs/superpowers/` | Đây là cây ứng dụng hiện tại. Không xóa cả thư mục hỗn hợp như `agents/`, `frontend/`, `sdk/`, `docs/` vì trong đó có file mới đang được Git theo dõi. |
| **Lưu tham khảo, chưa đưa vào PR Data Pack** | `daily report/`, `CHANGE_REQUESTS.md`, `PLAN.md`, `PROGRESS.md`, `outsources/`, phần `docs/` cũ về kiến trúc/contract/runbook (`docs/contracts/`, `docs/decisions/`, `docs/runbooks/`, `docs/architecture.md`, v.v.) | Có giá trị lịch sử nhưng phần lớn mô tả nền tảng trước khi đồng bộ ứng dụng. Chỉ đưa tài liệu liên quan và còn đúng vào PR; giữ bản trong Git history hoặc kho lưu trữ riêng trước khi dọn bản làm việc. |
| **Ứng viên bỏ khỏi thư mục làm việc sau khi đã lưu trữ/đối chiếu** | `src/`, `db/`, `schemas/`, `scripts/`, `test/`, `sdk/python/`, `agents/*.py` ở gốc `agents/`, `agents/manifests/`, `agents/pyproject.toml`, `agents/uv.lock` | Đây là mã, schema và test của nền tảng TypeScript/Hono/PostgreSQL cũ, hiện không nằm trong cây ứng dụng Python ở `HEAD`. Không đụng tới `agents/data/`, `agents/compare/` hoặc các agent plugin mới. |
| **Ứng viên bỏ cùng toolchain cũ** | `package.json` và `pnpm-lock.yaml` ở **gốc repo**, `tsconfig.json`, `tsconfig.build.json`, `vitest.config.ts`, `biome.json`, `versions.json`, `Dockerfile`, `docker/`, `.node-version`, `.env.example` ở **gốc repo** | Cấu hình của bản cũ; frontend hiện có `frontend/package.json` và `frontend/package-lock.json`, ứng dụng Python có `Dockerfile.python`. Kiểm tra tham chiếu còn dùng trước khi xóa; không xóa file cùng tên bên trong frontend/agent mới. |
| **Kiểm tra từng file, không xóa theo thư mục** | 8 file frontend khôi phục: `frontend/src/api/auth.ts`, `frontend/src/api/client.test.ts`, `frontend/src/components/inspector/RunPanel.tsx`, `frontend/src/events/parseEvent.ts`, `frontend/src/events/parseEvent.test.ts`, `frontend/src/events/useEventStream.test.ts`, `frontend/src/ui/runView.ts`, `frontend/src/ui/runView.test.ts` | Đây là file UI cũ chưa được theo dõi. Nếu tính năng còn cần thì chuyển sang API/UI mới; nếu không còn import hay kiểm thử tương ứng thì lưu lịch sử rồi bỏ. |
| **Tạm giữ để xác minh** | `LICENSE` | Không loại bỏ văn bản giấy phép chỉ vì file hiện chưa được theo dõi; cần đối chiếu quyền sử dụng và quyết định của chủ repo. |

### Việc nên làm tiếp theo cho Smart City

1. Tạo nhánh/PR riêng chỉ chứa Data Pack Smart City, migration và tài liệu cần thiết; không gom mã nền tảng cũ vào PR.
2. Sửa `project_key=1`, `project_id=PRJ-VHSC-HN`, dải `unit_key` bắt đầu từ 1 theo registry: `project_key=200`, `project_id=PRJ-VHSC`, `unit_key=200001–299999`. Registry quy định **`unit_code`** tiền tố `SMC-U` với số thứ tự 5 chữ số; CSV hiện dùng mã tòa/căn như `S1.01-09.02`, nên cần lưu mã cũ ở trường tham chiếu phù hợp nếu vẫn cần. Rà soát riêng `unit_id` kiểu `VHSC-U-...`. Quyết định cách biểu diễn 16 căn fixture `PRJ-VHSC-LEGAL-MOCK` mà vẫn giữ quy tắc một project key cho một pack; không tự ý nhập chúng thành dữ liệu dự án thật.
3. Sinh lại CSV và toàn bộ JSON kỳ vọng; chạy lại kiểm tra 16 bảng, khóa/FK, grain snapshot, 8 nguyên nhân, số dòng và truy vấn kịch bản. Ghi rõ số liệu QA mới thay cho kết quả ngày 25/09.
4. Thống nhất với nhóm cách nạp 16 bảng vào warehouse mà ứng dụng Python/SQLite hiện dùng, hoặc cấu hình một warehouse bất động sản riêng có adapter truy vấn; chỉ khi chạy truy vấn qua ứng dụng mới coi là tích hợp hoàn tất.

**Trạng thái dọn dẹp ngày 29/09/2026:** Đây chỉ là đề xuất. Chưa xóa, chuyển, stage hay sửa file nào khác.
