# Dọn repo cho Smart City Data Pack — 29/09/2026

## Mốc và nơi lưu bản cũ

- `origin/DATA` tại `a8bca11` đã publish `warehouse/id_registry.json` v3.1.1 và `warehouse/SNAPSHOT_RULES.md`; `origin/main` tại `aad64b7` là ứng dụng Python/SQLite.
- Commit khôi phục cũ `128d44e` từng đưa lại 471 file. Đã tạo nhánh sao lưu **local** `backup/DATA-NguyenQuangHuy-restore-2909` trỏ tới `1811af0` (gồm commit khôi phục và báo cáo 29/09 trước đợt dọn). Có thể lấy lại file cụ thể từ lịch sử này khi cần.
- Branch cá nhân đã merge `origin/DATA` ở `31d60fc`. Lần merge bỏ khỏi cây làm việc phần lớn mã nền tảng TypeScript/PostgreSQL cũ và đưa hai file N1 vào. Xung đột duy nhất ở `scripts/rehearse-backup-restore.sh` đã được giải quyết bằng cách bỏ script cũ.

## Quyết định cho cây file đang làm

| Nhóm | Quyết định và lý do | Trạng thái 29/09 |
| --- | --- | --- |
| Ứng dụng Python/SQLite hiện tại: `backend/`, plugin `agents/<tên-agent>/`, `sdk/vdagent_sdk/`, frontend mới, `pyproject.toml`, `uv.lock`, `Dockerfile.python`, `data/seed_warehouse.py` | **Giữ.** Đây là baseline chung của `main` và `DATA`; không xóa cả các thư mục hỗn hợp. | Giữ nguyên. |
| Hợp đồng chung: `warehouse/id_registry.json`, `warehouse/SNAPSHOT_RULES.md` | **Giữ** và kiểm N4 theo registry v3.1.1. | Đã có từ merge `DATA`. |
| N4 Smart City: `data/generate_vhsc_mock.py`, `data/mock/vhsc_20260630/`, tài liệu `data/*.md`, SQL QA/loader, `data/tests/`, `data/build_vhsc_sqlite.py`, `data/verify_vhsc_eval.py`, `migrations/`, `docs/data-warehouse-data-contract-v3.1.0.md` | **Giữ và cập nhật** để tái tạo 3.000 căn, 16 bảng, kiểm thử và phục vụ assembler N2. | Đã sửa/generate/QA trong đợt N4; rà diff trước PR. |
| Mã/toolchain cũ: `src/`, `db/`, `schemas/`, `scripts/`, `test/`, `sdk/python/`, file agent cũ ở gốc `agents/`, root `package.json`, `pnpm-lock.yaml`, `tsconfig*.json`, `vitest.config.ts`, `Dockerfile`, `docker/` | **Bỏ khỏi cây làm việc/PR.** Chúng thuộc nền tảng trước lần đồng bộ; bản khôi phục vẫn ở nhánh backup. | Đã được merge `DATA` loại khỏi cây hiện tại. |
| 3 báo cáo cũ `daily report/2409.md`, `2509.md`, `2809.md`; 3 file DOCX và 2 sơ đồ trong `docs/` | **Lưu trong nhánh backup, bỏ khỏi PR N4.** Đây là lịch sử/tham khảo nặng hoặc đã cũ; giữ báo cáo `2909.md` và contract Markdown đang được generator dùng. | Đã bỏ khỏi cây làm việc; có thể khôi phục từng file từ backup. |
| `CLEAN_UP.md` và `daily report/2909.md` | **Giữ** để truy vết quyết định, việc đã làm và việc còn phụ thuộc. | Đang cập nhật trong đợt N4. |
| `var/vhsc_warehouse.db` | **Giữ ở máy để smoke test**, không commit; `var/` đã được `.gitignore` loại trừ. Database PostgreSQL dev cũng chỉ là môi trường kiểm thử. | Đã tạo bản chiếu SQLite; hai database tạm kiểm migration đã được dọn. |

## Còn phải chốt trước khi hợp nhất chính thức

1. `TC-13/15` trong pack là giả định tạm vì chưa có ma trận test/BA; không đánh dấu là đạt TC chính thức.
2. `pack_manifest.json` là giao diện xuất đề xuất cho N2; cần Dũng xác nhận `assemble_dataset(pack_dir)` khi N2 xuất hiện.
3. PostgreSQL là nơi kiểm contract 16 bảng; bản chiếu SQLite chỉ chứng minh MCP SQL của backend đọc được dữ liệu. Backend mặc định và prompt Data Agent vẫn là demo bán lẻ; owner backend/Data cần quyết định cấu hình và kiểm hội thoại agent bất động sản.
4. Đã rà diff với `DATA` và mở [draft PR #6](https://github.com/HOANGQUANGMINH371195/Team_6_cAi/pull/6) chỉ gồm 40 file N4, hợp đồng và báo cáo/cleanup; không có mã nền tảng cũ trong diff. Nhánh backup và file `.env`/DB local không được push. PR còn ở dạng draft để nhóm review các phụ thuộc trên.

## Phase 2 — retire pipeline CSV warehouse (2026-10-04)

Production đọc AWS RDS `cdw` (schema `gold`, view `re`); dump `warehouse/backup/cdw_gold_snapshot_20260630.dump` là artifact DR chuẩn. Đã xoá khỏi repo (lịch sử Git vẫn giữ): `warehouse/dataset/` (dẫn xuất, còn 296.033 dòng off-snapshot không có trên AWS), `warehouse/project_{100..500}/`, `warehouse/shared/`, `warehouse/{organize_pack,assemble_dataset,verify_warehouse}.py`, `warehouse/tests/`, `warehouse/backup/build_backup.py`, bản trùng `warehouse/backup/cdw_gold_snapshot_20260630.sql`, bản chiếu SQLite `data/build_vhsc_sqlite.py` + `data/tests/test_vhsc_sqlite.py` (`var/vhsc_warehouse.db` không còn được dựng) và `docs/ASSEMBLE_DATASET_GUIDE.md`. Giữ lại tới Phase 3 cùng pack Smart City: `data/setup_dev.ps1`, `data/load_vhsc_mock.sql` (do `generate_vhsc_mock.py` sinh), `data/verify_vhsc_mock.sql`, `migrations/`. Raw pack nhóm C (`data/VGP/`, `data/masteri_cp/`, `data/risk_project_mock/`, `data/mock/vhsc_20260630/`, `warehouse/vhop/`) chưa đụng.

## Phase 3 — gỡ raw pack và local DW (2026-10-04)

Repo ứng dụng không còn lưu CSV dataset của warehouse. Đã gỡ khỏi cây làm việc (nguyên văn còn trong commit `aed2917`, có trên `origin/main`): raw pack `data/VGP/` (kèm generator và dbt project), `data/masteri_cp/`, `data/risk_project_mock/`, `data/mock/vhsc_20260630/`, `warehouse/vhop/`; generator/QA Smart City (`data/generate_vhsc_mock.py`, `data/verify_vhsc_eval.py`, `data/tests/`, `data/{qa_results,scenario_coverage,source_map}.md`); PostgreSQL dev cục bộ (`data/setup_dev.ps1`, `data/{load,verify}_vhsc_mock.sql`, `migrations/`); code chết `backend/vdagent_backend/warehouse/selection.py` + test của nó. Danh sách từng file, sha256, git blob, phân loại (UNIQUE_ARCHIVAL / REGENERATABLE / OBSOLETE) và lệnh khôi phục: `docs/data-archive/phase3-manifest.json`. Pack Smart City tái tạo được byte-identical từ generator ở commit đó (đã kiểm); pack VGP chưa kiểm được tái tạo (thiếu pandas/numpy/duckdb) nên khôi phục bằng Git.

## Phase 4 — gỡ nền tảng TypeScript cũ (2026-10-04)

Đã gỡ khỏi cây làm việc (còn nguyên trong commit `aed2917`): `src/`, `test/`, `db/`, `schemas/`, `sdk/python/`, các file agent cũ ở gốc `agents/` và `agents/manifests/`, root `package.json`, `pnpm-lock.yaml`, `tsconfig*.json`, `vitest.config.ts`, `versions.json`, `biome.json`, `.node-version`, toàn bộ tooling `scripts/` cũ, root `Dockerfile`, `docker-compose.override.yml` và 4 file Docker chỉ dùng cho nền tảng TS. Thay thế: quét secret bằng `make secret-check` (`scripts/check_secrets.py`); frontend tự quản Node (Node 22 theo `Dockerfile.python`). Tài liệu nền tảng cũ được giữ với banner "Historical"; chỉ mục tài liệu hiện hành là `docs/README.md`. Chi tiết: `AGENTS.md` §25.

## Phase 5 — gỡ backend-v1 và test cũ (2026-10-04)

Đã gỡ các module backend-v1 chết (`backend/vdagent_backend/{api,db,engine}/`, `events.py`, `ids.py`, `tokens.py`, `plugins.py`, `mcp/{tools,charts,sql}.py`) và 3 file test v1 trùng lặp ở `backend/tests/` (bản v2 nằm ở `http/`, `runtime/`, `memory/`). Kết quả: test host và Docker 0 lỗi; acceptance lineage 7/7 sau khi cập nhật 2 con số theo thay đổi có chủ đích ở commit `957747f`; `uv.lock` được lock lại (không đổi dependency). Chi tiết: `AGENTS.md` §26.

## Phase 6A/6B — dọn tài liệu (2026-10-04)

6A gom tài liệu hiện hành về một bộ chuẩn (`docs/README.md` là mục lục; `architecture/`, `contracts/`, `agents/`,
`testing/`, `security/`, `frontend/`, `product/`) và rút `AGENTS.md` còn quy tắc + trạng thái kiểm chứng. 6B chuyển
toàn bộ tài liệu lịch sử vào `docs/archive/` bằng `git mv` (nền tảng TypeScript cũ, tích hợp 2026-09 kèm bằng chứng,
kế hoạch refactor, contract agent cũ, đặc tả thiết kế có ngày, lịch sử `AGENTS.md`; xem `docs/archive/README.md`), không
xoá file nào ở 6B. Không ảnh hưởng runtime: chỉ đổi tài liệu và 7 dòng comment/docstring trỏ tới đường dẫn tài liệu cũ.
