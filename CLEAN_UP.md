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
4. PR N4 chỉ nên đưa các file ở nhóm N4, hợp đồng cần thiết và báo cáo/cleanup liên quan; tự rà `git diff origin/DATA` trước khi push. Không đẩy nhánh backup hoặc file `.env`/DB local.
