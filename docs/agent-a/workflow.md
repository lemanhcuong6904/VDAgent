# Quy trình làm việc team AGENT_A

Tài liệu này quy định cách team AGENT_A (Orchestrator, Data, Report) nhận task, code, review và
đưa code lên `develop`. Nó bổ sung cho [`GIT_RULE.md`](../../GIT_RULE.md) và
[folder ownership](../folder-ownership.md). Khi hai nơi nói khác nhau, `GIT_RULE.md` thắng.

## 1. Vai trò và nhánh

| Vai trò | Phụ trách | Nhánh làm việc |
| --- | --- | --- |
| Lead AGENT_A | Chốt contract, duyệt PR vào `AGENT_A`, mở PR `AGENT_A → develop` | `AGENT_A` |
| Orchestrator | `src/agents/orchestrator/`, phần điều phối trong `src/agents/analytics.ts` | `feature/orchestrator_agent` |
| Data | `src/agents/data/` | `feature/data_agent` |
| Report | `src/agents/report/`, fallback report trong `analytics.ts` | `feature/report_agent` |
| Data test | `test/agent-a-*`, `test/fixtures/agent-a/`, golden set, eval | `feature/data_test` |

Các agent `compare`, `insight`, `visualize` và mọi file ngoài bảng trên thuộc team khác. Không
sửa trực tiếp; cần thay đổi thì mở issue hoặc nhắn owner (mục 7).

```text
feature/orchestrator_agent ─┐
feature/data_agent ─────────┤  PR, lead review, merge commit
feature/report_agent ───────┼──────────────────────────────▶ AGENT_A ──PR──▶ develop
feature/data_test ──────────┘
```

## 2. Tài liệu của team

Toàn bộ tài liệu của team nằm trong `docs/agent-a/`. Xem danh sách đầy đủ và trạng thái từng
tài liệu tại [README](README.md).

| Tài liệu | Nội dung | Ai được sửa |
| --- | --- | --- |
| `workflow.md` | Quy trình (tài liệu này) | Lead |
| `contracts.md` | StepSpec, Envelope, mã lỗi, format ID, nhãn `[agent]`: nguồn sự thật chung | Lead duyệt mọi thay đổi |
| `testing.md` | Fixture, golden set, eval E1–E8 | Data test + lead |
| `orchestrator/` | Thiết kế và đặc tả Orchestrator | Orchestrator + lead |
| `data/` | Thiết kế và đặc tả Data Agent, gate G0–G6 | Data + lead |
| `report/` | Thiết kế và đặc tả Report | Report + lead |

Khi `contracts.md` chưa có, mục 3 của [`data/spec.md`](data/spec.md) được dùng làm contract tạm.

Quy tắc: **code đổi hành vi thì tài liệu đổi trong cùng PR.** PR đổi contract mà không đổi tài
liệu contract sẽ bị trả lại.

## 3. Task và gate

### 3.1. Mã task

Mỗi task có mã theo người làm và gate: `D-23` (Data, gate G2), `O-10` (Orchestrator), `R-40`
(Report), `DT-20` (Data test), `L-01` (Lead). Danh sách task nằm trong tài liệu đặc tả của từng
agent.

Mỗi task là **một GitHub issue**:

- Tiêu đề: `[D-23] Compile data plan to SQL with lineage`
- Label: `agent-a`, `gate:G2`, `area:data` (hoặc `area:orchestrator`, `area:report`, `area:test`)
- Mô tả: mục tiêu, file dự kiến chạm, tiêu chí xong, task phụ thuộc (`blocked by #…`)
- Người nhận tự assign trước khi bắt đầu, để không ai làm trùng

### 3.2. Vòng đời task

```text
Todo → In progress → In review → Done
          │               │
          └── Blocked ◀───┘   (ghi rõ chặn bởi ai/issue nào)
```

- **In progress:** đã tạo commit đầu tiên trên nhánh feature.
- **In review:** đã mở PR vào `AGENT_A`.
- **Done:** PR đã merge. Issue đóng tự động nhờ `Closes #…` trong PR.
- Bị chặn quá 1 ngày làm việc thì báo lead ngay trong ngày, không chờ tới buổi họp.

### 3.3. Gate

Gate là mốc mà **cả team** phải cùng đạt trước khi làm tiếp. Nếu một phần chưa xong thì chưa
được qua gate.

- Mỗi gate có danh sách task và **tiêu chí thoát** trong tài liệu đặc tả.
- Khi mọi task của gate đã Done, lead mở **issue gate review** `[G2] Gate review`, liệt kê từng
  tiêu chí thoát kèm bằng chứng (link PR, output test, điểm eval).
- Qua gate: lead mở PR `AGENT_A → develop` với tiêu đề `feat(agents): complete gate G2 ...`.
- Không qua: ghi lại tiêu chí nào trượt, tạo task sửa, gate vẫn mở.
- Task của gate sau được làm trước nếu không phụ thuộc gate hiện tại, nhưng **không merge vào
  `AGENT_A`** nếu nó đổi contract chưa chốt.

## 4. Luồng code hằng ngày

### 4.1. Bắt đầu

```sh
git fetch origin
git switch feature/<nhánh-của-mình>
git pull --ff-only origin feature/<nhánh-của-mình>
git merge origin/AGENT_A           # lấy code đã merge của các bạn khác
corepack pnpm test
```

Cập nhật từ `AGENT_A` **ít nhất mỗi ngày làm việc** và luôn cập nhật trước khi mở PR. Dùng
`merge`, không `rebase`, vì nhánh feature có thể có người khác cùng dùng.

### 4.2. Commit

Theo Conventional Commits (`GIT_RULE.md` mục 4). Scope của team:

| Scope | Dùng khi |
| --- | --- |
| `orchestrator` | Orchestrator, routing, `runAnalyticsWorkflow`, `sanitizeFinalAnswer` |
| `data-agent` | Data Agent (tránh trùng scope `data` của team DATA) |
| `report` | Report Agent, fallback report |
| `agents` | Thay đổi dùng chung trong `analytics.ts` hoặc contract |

Commit chỉ thêm test dùng type `test` với scope của agent, ví dụ `test(data-agent): ...`.

- Mỗi commit là một thay đổi logic và tự pass test. Thứ tự nên làm: test tái hiện → sửa/thêm tính
  năng → refactor → test biên → docs.
- Body commit giải thích *vì sao*, nhất là khi đổi prompt hoặc contract.
- Không commit `wip`, `update`, `fix` trống nghĩa vào nhánh sắp mở PR.

### 4.3. Trước khi push

```sh
corepack pnpm format
corepack pnpm lint
corepack pnpm check
corepack pnpm test
git diff --check
```

Chạm frontend thì chạy thêm `corepack pnpm frontend:build` và `npm --prefix frontend test`.

## 5. Pull request vào `AGENT_A`

### 5.1. Mẫu mô tả PR

```md
## Task
Closes #<issue> — [D-23] <tên task> (Gate G2)

## Thay đổi
- ...

## Contract
- [ ] Không đổi contract
- [ ] Có đổi: <trường nào, version cũ → mới>, đã cập nhật docs/agent-a/contracts.md

## Trước / sau (bắt buộc khi đổi prompt, routing hoặc output agent)
Input: ...
Output trước: ...
Output sau: ...

## Kiểm tra
- [ ] lint · check · test pass
- [ ] Test mới: <tên file/case>, gồm nhánh lỗi và abort
- [ ] Golden/eval (nếu có): E2 ..., E6 = 0

## Ảnh hưởng ngoài team
<không có | owner cần review: ...>
```

### 5.2. Quy tắc

- PR nhỏ hơn khoảng 400 dòng thay đổi thực tế. Lớn hơn thì tách theo task.
- Chỉ chạm vùng của mình (mục 1). Chạm file của người khác trong team thì tag người đó review.
- Lead review trong **1 ngày làm việc**. Comment yêu cầu sửa phải được giải quyết trước khi merge.
- Merge bằng **"Create a merge commit"**, không squash, để giữ lịch sử từng commit và tác giả.
- Không tự merge PR của mình, kể cả lead. PR của lead do một thành viên khác review.

## 6. Vùng dễ conflict

| File | Ai hay sửa | Cách tránh |
| --- | --- | --- |
| `src/agents/analytics.ts` | Orchestrator, Data, Report | Mỗi người chỉ sửa hàm của agent mình (bảng dưới). Tách logic mới sang file trong thư mục agent thay vì thêm vào `analytics.ts` |
| Contract (`src/agents/data/contract.ts`) | Data, Orchestrator, Report | Chỉ sửa qua PR có lead duyệt; báo trước trong nhóm chat |
| `test/agent-plugins.test.ts` | Cả team | Test mới đặt trong file `test/agent-a-*.test.ts` riêng |
| `test/fixtures/agent-a/` | Data test | Người khác cần thêm fixture thì nhờ Data test hoặc PR nhỏ riêng |

Phân chia hàm trong `src/agents/analytics.ts` (file dùng chung cho cả 6 agent):

| Hàm | Người sửa |
| --- | --- |
| `runAnalyticsWorkflow`, `isAnalyticsRequest`, `needsComparison`, `needsInsight`, `needsReport`, `sanitizeFinalAnswer`, `delegateTo`, `clip` | Orchestrator |
| `prepareNamedTable`, `extractDatasetId` | Data |
| `createFallbackReport`, `extractSpecialistResult`, `shortFinding`, `formatCell` | Report |
| `createAnalyticsAgent` (descriptor, input schema, guardrails) | Lead duyệt, vì ảnh hưởng cả 6 agent và cần báo CORE |
| `createFallbackVisualization` | Không sửa, thuộc team sở hữu `visualize` |

Khi conflict: người mở PR tự resolve. Nếu phần conflict là logic của người khác, hỏi người đó
trước khi chọn, rồi chạy lại toàn bộ test.

## 7. Đổi contract và phối hợp ngoài team

**Trong team** (StepSpec, Envelope, mã lỗi, format ID):

1. Mở issue `[CONTRACT] <mô tả>`, nêu lý do và agent bị ảnh hưởng.
2. Lead và owner các agent bị ảnh hưởng đồng ý trong issue.
3. Một PR cập nhật `contract.ts`, `docs/agent-a/contracts.md`, tăng `contract_version` và sửa mọi
   agent dùng nó. Nếu quá lớn thì tách thành PR liền nhau, và **không merge PR đầu một mình**.

**Ngoài team:** không sửa file của họ. Lead mở issue hoặc nhắn owner:

| Cần | Owner |
| --- | --- |
| Warehouse provider, tool `warehouse.*` | DATA |
| Migration, bảng `web_*` | Data persistence |
| `agents.delegate`, `AgentPlugin`, tool pool, roster | CORE |
| Message gửi tới `compare`, `insight`, `visualize` | Team sở hữu các agent đó |
| Hiển thị trên UI | PRODUCT |

## 8. Định nghĩa "xong"

Một task chỉ xong khi đủ các điều sau:

- [ ] Code merged vào `AGENT_A` qua PR đã được review
- [ ] Có test offline cho luồng đúng, nhánh lỗi và `signal` abort
- [ ] Không test cũ nào bị tắt hoặc skip để PR pass
- [ ] Tài liệu đặc tả/contract khớp với code
- [ ] Không có secret, dữ liệu thật hoặc output debug trong code
- [ ] Issue đã đóng và có link PR

## 9. Nhịp làm việc

| Khi nào | Việc | Ai |
| --- | --- | --- |
| Mỗi ngày | Cập nhật trạng thái issue; báo blocked | Cả team |
| Mỗi ngày | Review PR đang chờ | Lead |
| Khi gate đủ task | Gate review, PR `AGENT_A → develop` | Lead + cả team |
| Mỗi tuần | Đọc 20 trace ngẫu nhiên + mọi trace sai, thêm task vào golden set | Data test + Data |
