# GIT RULES

Quy ước làm việc với Git dành cho dự án và đội ngũ khoảng 30 người.
Mục tiêu là giữ lịch sử dễ đọc, giảm xung đột khi tích hợp và bảo đảm mọi thay đổi
đều có người chịu trách nhiệm, được kiểm tra và có thể truy vết.

## 1. Nguyên tắc chung

- Mọi thay đổi phải đi qua Pull Request (PR), trừ trường hợp xử lý sự cố khẩn cấp
  theo mục `Hotfix`.
- Không commit trực tiếp vào `main`, `develop` hoặc các nhánh release.
- Mỗi nhánh chỉ nên phục vụ một issue hoặc một mục tiêu rõ ràng.
- Không commit mã nguồn chưa chạy được, secret, token, mật khẩu, file build hoặc
  dữ liệu cá nhân vào repository.
- PR phải nhỏ và tập trung. Nếu thay đổi lớn, tách thành các PR có thể merge độc lập.
- Không rewrite lịch sử của nhánh dùng chung. Chỉ được `rebase` trên nhánh cá nhân
  chưa được người khác sử dụng.

## 2. Mô hình nhánh và quyền truy cập

Dự án sử dụng các nhánh cá nhân theo nhóm và tên thành viên, cùng các nhánh điều phối
`develop`, `release/*` và `main`.

Mỗi thành viên bắt buộc làm việc trên một nhánh riêng có dạng
`<TÊN_NHÓM>-<TênThànhViên>`. Ví dụ: `DATA-NguyenTuanAnh`.

Các mẫu nhánh cá nhân theo nhóm là:

| Mẫu tên nhánh | Nhóm phụ trách | Ai được push | Ai được đưa code lên nhánh kế tiếp |
|---|---|---|---|
| `<CORE>-<TênThànhViên>` | Nhóm CORE | Thành viên đó và team lead CORE | Team lead CORE đưa lên `develop` |
| `<AGENT_A>-<TênThànhViên>` | Nhóm AGENT_A | Thành viên đó và team lead AGENT_A | Team lead AGENT_A đưa lên `develop` |
| `<AGENT_B>-<TênThànhViên>` | Nhóm AGENT_B | Thành viên đó và team lead AGENT_B | Team lead AGENT_B đưa lên `develop` |
| `<DATA>-<TênThànhViên>` | Nhóm DATA | Thành viên đó và team lead DATA | Team lead DATA đưa lên `develop` |
| `<PRODUCT>-<TênThànhViên>` | Nhóm PRODUCT | Thành viên đó và team lead PRODUCT | Team lead PRODUCT đưa lên `develop` |

Các nhánh dùng chung:

| Nhánh | Mục đích | Quyền ghi |
|---|---|---|
| `develop` | Tích hợp code từ các team | Chỉ team lead của team tương ứng có quyền ghi/merge phần thay đổi của team đó |
| `release/*` | Chuẩn bị phiên bản phát hành từ `develop` | Team lead phụ trách thay đổi và release manager theo phạm vi release |
| `main` | Phiên bản ổn định/production | Bắt buộc 2 approvals: CORE lead và 1 team lead khác |

### Luồng bắt buộc

```text
Thành viên team
    ↓ push/PR
Nhánh cá nhân theo nhóm (ví dụ: DATA-NguyenTuanAnh)
    ↓ team lead kiểm tra và merge
develop
    ↓ team lead của phần thay đổi phê duyệt
release/* hoặc main
```

Quy tắc bắt buộc:

- Thành viên chỉ được push vào nhánh cá nhân của chính mình, đặt theo mẫu tên nhóm
  và tên thành viên.
- Thành viên không được push trực tiếp vào `develop`, `release/*` hoặc `main`.
- Chỉ team lead của team có thay đổi được cấp quyền ghi và merge PR từ các nhánh cá
  nhân của team đó vào `develop`. Quy trình chuẩn vẫn là team lead merge PR, không
  push tùy ý.
- Đưa code từ nhánh cá nhân lên `release/*` cần team lead của team đó approve và
  release manager kiểm tra phạm vi phát hành.
- Đưa code lên `main` bắt buộc có đúng 2 approvals: CORE lead và 1 team lead khác.
- CORE lead không được tự approve một mình; approval thứ hai phải đến từ team lead
  của `AGENT_A`, `AGENT_B`, `DATA` hoặc `PRODUCT`.
- Mỗi thành viên phải dùng nhánh riêng có tên theo đúng mẫu
  `<TÊN_NHÓM>-<TênThànhViên>`; ví dụ `DATA-NguyenTuanAnh`.
- Nhánh cá nhân đang có PR hoặc công việc chưa hoàn tất không được xóa.

Tên nhánh cá nhân bắt buộc có dạng `<TÊN_NHÓM>-<TênThànhViên>`, trong đó tên nhóm
viết đúng chữ hoa và tên thành viên phải thể hiện rõ người sở hữu. Không dùng tên
chung như `DATA-dev`, `DATA-new` hoặc `data-nguyentuananh`.

## 3. Quy trình làm việc hằng ngày

Trước khi bắt đầu:

```bash
git fetch origin
git switch DATA-NguyenTuanAnh  # thay bằng nhánh cá nhân của thành viên
git pull --ff-only origin DATA-NguyenTuanAnh
```

Trong quá trình làm việc:

1. Chỉ push thay đổi vào nhánh cá nhân của mình theo đúng mẫu tên nhóm và tên thành viên.
2. Commit thường xuyên theo từng thay đổi logic hoàn chỉnh.
3. Chạy formatter, linter, test và build tương ứng trước khi push.
4. Mở PR từ nhánh cá nhân lên `develop` khi team lead đã kiểm tra nội bộ.
5. Xử lý toàn bộ comment review trước khi yêu cầu approve lại.

Trước khi team lead merge vào `develop`:

```bash
git fetch origin
git switch DATA-NguyenTuanAnh  # thay bằng nhánh cá nhân thuộc team tương ứng
git pull --ff-only origin DATA-NguyenTuanAnh
# cập nhật/kiểm tra theo quy trình của team
# chạy formatter, lint, test và build của dự án
```

Team lead chỉ được merge sau khi CI xanh, review nội bộ hoàn tất và PR có liên kết
đến issue/task. Không force push vào bất kỳ nhánh cá nhân nào.

## 4. Quy ước commit

Dùng Conventional Commits:

```text
<type>(<scope>): <mô tả ngắn>
```

Các `type` được phép:

- `feat`: thêm chức năng.
- `fix`: sửa lỗi.
- `refactor`: thay đổi cấu trúc nhưng không đổi hành vi.
- `perf`: cải thiện hiệu năng.
- `test`: thêm hoặc sửa test.
- `docs`: thay đổi tài liệu.
- `build`: thay đổi build hoặc dependency.
- `ci`: thay đổi pipeline CI/CD.
- `chore`: công việc bảo trì khác.
- `revert`: hoàn tác một commit.

Ví dụ tốt:

```text
feat(auth): add refresh token rotation
fix(api): return 404 when project is missing
test(user): cover duplicate email validation
```

Quy tắc viết commit:

- Dùng động từ mệnh lệnh, viết ngắn gọn, tối đa khoảng 72 ký tự ở dòng đầu.
- Không gộp các thay đổi không liên quan vào cùng một commit.
- Body của commit nên giải thích lý do hoặc tác động khi nội dung không tự rõ ràng.
- Dùng `BREAKING CHANGE:` trong footer hoặc thêm `!` sau type/scope khi phá vỡ API.
- Không dùng commit kiểu `update`, `fix`, `changes`, `final`, `wip` trên nhánh sắp mở PR.

## 5. Pull Request

Tiêu đề PR dùng cùng định dạng với commit, ví dụ:

```text
feat(auth): support Google OAuth login
```

Mỗi PR phải có:

- Liên kết issue/task và mô tả vấn đề cần giải quyết.
- Mô tả cách triển khai và các quyết định kỹ thuật quan trọng.
- Phạm vi ảnh hưởng, migration hoặc thay đổi cấu hình nếu có.
- Hướng dẫn kiểm thử hoặc bằng chứng test đã chạy.
- Ghi chú triển khai, rollback và thay đổi biến môi trường nếu có.
- Danh sách reviewer phù hợp với phần mã bị thay đổi.

Kích thước PR nên dưới khoảng 400 dòng thay đổi thực tế. PR lớn hơn phải nêu rõ lý
do và chia thành các bước review được. Không mở PR ở trạng thái Draft cho đến khi
đã có phần triển khai đủ để reviewer đánh giá hướng đi.

### Quy tắc review

- PR từ team lên `develop` hoặc `release/*` cần team lead của chính team đó approve.
- PR từ `develop` hoặc `release/*` lên `main` cần đúng 2 approvals: CORE lead và
  1 team lead khác.
- Thay đổi ảnh hưởng tới bảo mật, dữ liệu, public API hoặc kiến trúc cần thêm
  approval của owner/chuyên gia phụ trách.
- Tác giả không tự approve PR của mình.
- Reviewer phải kiểm tra đúng/sai của logic, test, bảo mật, hiệu năng và khả năng
  vận hành; không chỉ kiểm tra format.
- Comment yêu cầu sửa phải được giải quyết hoặc chuyển thành issue có người phụ trách.
- Không merge khi CI thất bại, có conflict hoặc có approval bị dismiss sau thay đổi.
- Tác giả chịu trách nhiệm cuối cùng về việc PR đã sẵn sàng merge.

## 6. Bảo vệ repository và phân quyền

Repository nên cấu hình các branch protection rule sau:

- Bắt buộc PR cho mọi lần đưa code từ nhánh cá nhân lên `develop` hoặc `release/*`.
- Bắt buộc PR từ `develop` hoặc `release/*` lên `main` có 2 approvals: CORE lead
  và 1 team lead khác.
- Bắt buộc tất cả required status checks phải pass.
- Bắt buộc PR phải cập nhật với branch đích trước khi merge.
- Cấm force push và cấm xóa các nhánh cá nhân đang có công việc, cùng `main`,
  `develop`, `release/*`, `hotfix/*`.
- Chỉ team lead tương ứng được merge PR team vào `develop` hoặc `release/*`.
- Chỉ release manager/maintainer được hoàn tất merge vào `main` sau khi có đủ 2
  approvals bắt buộc.
- Bật CODEOWNERS để tự động chọn team lead phù hợp theo thư mục.
- Bật secret scanning, dependency scanning và kiểm tra license trong CI.
- Chỉ cho phép merge qua PR; cấm bypass branch protection kể cả với administrator,
  ngoại trừ quy trình hotfix đã được ghi nhận.

Phân quyền đề xuất cho đội 30 người:

- 1–2 repository administrators: quản lý quyền, rule và cài đặt bảo mật.
- 5 team lead: mỗi team một người, có quyền review/merge từ các nhánh cá nhân
  thuộc team mình lên `develop` và `release/*`; không tự cấp quyền thay team khác.
- CORE lead là người bắt buộc approve mọi thay đổi đưa lên `main`.
- 1 release manager: chỉ thực hiện merge vào `main` sau khi có CORE lead và một team
  lead khác approve.
- Các thành viên còn lại: chỉ push vào nhánh cá nhân đúng mẫu của mình và tạo PR.
- Không dùng tài khoản dùng chung; mỗi người phải dùng tài khoản cá nhân và MFA.

## 7. Merge và phát hành

### Merge vào `develop`

PR từ các nhánh cá nhân thuộc `CORE`, `AGENT_A`, `AGENT_B`, `DATA` hoặc `PRODUCT`
chỉ được merge vào `develop` hoặc `release/*` khi team lead tương ứng đã approve,
CI xanh, không còn conflict và issue ở trạng thái phù hợp.
Team lead chịu trách nhiệm kiểm tra tác động tới các team khác trước khi merge.

### Merge vào `main`

1. Release manager tạo PR từ `develop` lên `main` hoặc qua `release/*` theo kế hoạch.
2. CI, regression test, migration và changelog phải hoàn tất.
3. CORE lead và đúng một team lead khác phải approve độc lập trên cùng PR.
4. Chỉ sau khi đủ 2 approvals bắt buộc, release manager/maintainer mới được merge
   vào `main`.
5. Nếu code thay đổi sau bất kỳ approval nào, cả hai người bắt buộc phải review lại.

### Release

1. Tạo `release/vX.Y.Z` từ `develop`.
2. Cập nhật changelog, version và migration cần thiết.
3. Chỉ nhận bugfix, tài liệu và thay đổi release trên branch này.
4. Chạy regression test và tạo PR vào `main`.
5. Team lead của phần thay đổi phải approve PR release; CORE lead và một team lead
   khác phải approve nếu PR release được đưa tiếp lên `main`.
6. Sau khi merge, tạo annotated tag và phát hành artifact.
7. Merge hoặc cherry-pick các thay đổi release trở lại `develop`.

Tag dùng Semantic Versioning:

```text
vMAJOR.MINOR.PATCH
```

- `MAJOR`: thay đổi không tương thích.
- `MINOR`: thêm chức năng tương thích ngược.
- `PATCH`: sửa lỗi tương thích ngược.

Ví dụ:

```bash
git tag -a v1.4.0 -m "Release v1.4.0"
git push origin v1.4.0
```

### Hotfix

Với lỗi ảnh hưởng production, tạo `hotfix/*` từ tag hoặc `main`, giữ phạm vi nhỏ,
ghi rõ mức độ ảnh hưởng và kế hoạch rollback. Hotfix vẫn cần một reviewer khác và
CI tối thiểu. Sau khi phát hành, bắt buộc đưa cùng thay đổi về `develop` để tránh
lỗi quay lại ở release sau.

## 8. Xử lý conflict và lịch sử Git

- Luôn cập nhật branch trước khi bắt đầu giải quyết conflict.
- Người tạo PR là người giải quyết conflict, vì họ hiểu ý định thay đổi của mình.
- Khi conflict liên quan tới logic quan trọng, trao đổi trực tiếp với owner của phần
  mã trước khi chọn phương án.
- Sau khi resolve conflict, chạy lại test liên quan; không chỉ kiểm tra việc Git đã
  tạo được commit.
- Ưu tiên `rebase` trên branch cá nhân để lịch sử gọn. Dùng `merge` khi branch đã
  được nhiều người cùng làm hoặc việc rebase có nguy cơ làm mất ngữ cảnh.

## 9. Secret, dữ liệu và file sinh tự động

Không commit các loại sau:

- API key, access token, private key, password, cookie hoặc file `.env` thật.
- Dữ liệu khách hàng, dữ liệu production, log chứa thông tin định danh.
- Thư mục build, cache, IDE settings cá nhân và dependency đã được quản lý bởi package manager.

Nếu lỡ commit secret:

1. Thu hồi và rotate secret ngay lập tức.
2. Báo cho maintainer/security owner.
3. Xóa secret khỏi lịch sử bằng công cụ được phê duyệt sau khi đã bảo toàn bằng chứng cần thiết.
4. Không coi việc xóa file ở commit mới là đã xử lý xong.

## 10. Quy tắc tối thiểu cho CI

Mọi PR nên chạy tự động:

- Format check.
- Lint/static analysis.
- Unit test và integration test phù hợp.
- Build/package.
- Security/dependency scan.
- Kiểm tra migration hoặc contract/API khi có liên quan.

CI phải chạy lại khi có commit mới. Không bỏ qua required check bằng cách tắt job,
đổi tên check hoặc merge thủ công.

## 11. Checklist trước khi mở PR

- [ ] Branch bắt đầu từ branch đích mới nhất.
- [ ] Tên branch và commit đúng quy ước.
- [ ] PR liên kết với issue/task.
- [ ] Code đã được format và lint.
- [ ] Test phù hợp đã chạy thành công.
- [ ] Không có secret, dữ liệu nhạy cảm hoặc file sinh tự động.
- [ ] Đã cập nhật tài liệu, migration, changelog hoặc cấu hình nếu cần.
- [ ] Đã tự review diff và kiểm tra các file ngoài phạm vi.
- [ ] Đã chọn đúng reviewer/owner.

## 12. Ngoại lệ

Ngoại lệ chỉ áp dụng khi có lý do kỹ thuật hoặc vận hành rõ ràng. Người yêu cầu
ngoại lệ phải ghi lý do, phạm vi, người phê duyệt và kế hoạch hoàn nguyên trong issue
hoặc PR. Maintainer có quyền từ chối ngoại lệ nếu làm tăng rủi ro mất dữ liệu, lộ
secret hoặc phá vỡ khả năng truy vết.

Quy ước này được xem xét lại mỗi quý hoặc sau một sự cố liên quan đến quy trình Git.
