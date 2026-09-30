# Quy tắc Git cho tích hợp Data Warehouse

Tài liệu này là checklist thực thi cho các thay đổi ở `data/` và `warehouse/`. Quy định đầy đủ vẫn là [GIT_RULE.md](../GIT_RULE.md).

## Branch và Pull Request

- Làm việc trên branch cá nhân theo mẫu `DATA-<TenThanhVien>`; không commit trực tiếp vào `develop`, `release/*` hoặc `main`.
- Mỗi PR chỉ phục vụ một mục tiêu rõ ràng. Tích hợp mỗi project nên có commit hoặc PR riêng khi khả thi.
- PR vào `develop` cần team lead DATA review, CI xanh, không conflict và liên kết task/issue.
- Không force-push hoặc rewrite lịch sử của branch dùng chung.

## Commit

- Dùng Conventional Commits: `<type>(<scope>): <mô tả ngắn>`.
- Giữ commit theo một thay đổi logic hoàn chỉnh; không dùng `wip`, `update`, `final` hay `changes`.
- Tự review `git diff --cached` trước khi commit và ghi body khi tác động không hiển nhiên.
- Ví dụ: `feat(warehouse): add project 500 canonical pack`.

## Dữ liệu Warehouse

- Chỉ nhận dữ liệu mock/synthetic đã được task phê duyệt; không đưa dữ liệu khách hàng, production, secret, `.env`, log, cache hoặc artefact build vào Git.
- Raw input phải nằm dưới `data/<project>/csv`; canonical output phải nằm dưới `warehouse/project_<key>/`.
- Mọi project phải dùng đúng `project_key`, `project_id`, dải `zone_key`, `channel_key`, `infra_key` theo `warehouse/id_registry.json`.
- Chạy `python warehouse/organize_pack.py` và `python warehouse/verify_warehouse.py` trước khi mở PR; quality gate phải pass toàn bộ project đã tích hợp.

## Ngoại lệ dữ liệu lớn

CSV mock cho project 400 và 500 là fixture cần thiết để tái tạo canonical warehouse pack. Chúng được cho phép trong phạm vi thay đổi này vì không chứa dữ liệu production hay định danh cá nhân. PR phải nêu rõ nguồn, kích thước, kết quả quality gate và cách rollback (revert commit tích hợp).

## Checklist trước PR

- [ ] Branch đúng mẫu và cập nhật từ branch đích.
- [ ] Commit message đúng Conventional Commits, phạm vi tập trung.
- [ ] Không có secret, cache, log hoặc artefact build trong staged files.
- [ ] `organize_pack.py` và `verify_warehouse.py` chạy thành công.
- [ ] PR nêu nguồn dữ liệu, re-key/migration, kiểm thử và rollback.
- [ ] Team lead DATA và các owner liên quan được mời review.
