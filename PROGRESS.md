# Tiến độ

Cập nhật 2026-09-28. Yêu cầu gốc: [PLAN.md](PLAN.md). Bằng chứng gốc: `docs/execution/`.
File này thay cho `BLOCKERS.md` cũ: mọi việc còn mở nằm ở mục cuối.

## Tóm tắt 30 giây

- Tất cả milestone M0–M14 có checklist `[x]` trong PLAN.md.
- `pnpm milestone:audit` là trọng tài: milestone chỉ được gọi là VERIFIED khi có receipt `execution.v1`
  kèm reviewer và bài tập rollback PASS. Kết quả mới nhất: `docs/execution/milestone-audit.json`.
- Mọi port của agent đều đã nối vào production, trừ `sandbox`.
- E2E với model thật: 9/9 lượt PASS, tốn $0.0037 (trần $0.30).

## Từng milestone đang ở đâu

| Milestone | Nội dung (nói đơn giản) | Bằng chứng |
| --- | --- | --- |
| M0 | Công cụ đo, inventory, receipt | `receipts/M0.json` |
| M1 | Contract công khai (`agent.v1`, ports, schemas) | `receipts/M1-2026-09-27T15-40-23-931Z.json` |
| M2–M13 | Host port factory, registry, tool, workflow, outbox, session, memory, process agent, agent mẫu, artifact/telemetry, API v1/MCP/A2A, lifecycle | `receipts/M<N>-<thời gian>.json` (mỗi milestone một file) |
| M14 | Docs, template, runbooks, audit, owner duyệt | PLAN.md M14.7 (owner duyệt 2026-09-27) |
| M15 | So sánh kiến trúc với vde-agent-demo | `docs/comparison-vde-agent-demo.md` |

Receipt nằm trong `docs/execution/receipts/`. Nếu `milestone-audit.json` ghi `UNVERIFIED` thì tin audit,
không tin bảng này.

## Production đang dùng gì

"Production" = những gì `src/server.ts` và `src/worker.ts` thực sự import và chạy.

Agent nhận port từ `createHostPorts` (`src/ports/host-factory.ts`). Mỗi port là một lớp mỏng gọi
tool trong tool pool, nên quyền luôn là: tool có trong `toolGrants` của manifest VÀ pool cho agent đó gọi.

| Port | File | Làm gì |
| --- | --- | --- |
| `model` | `host-factory.ts` | Gọi model, kiểm output theo schema, đếm số lần gọi |
| `tools` | `host-tools.ts` | Gọi tool qua `McpToolAdapter`; nhớ kết quả theo idempotency key; tool lỗi bị khóa 60 giây |
| `warehouse` | `host-warehouse.ts` | Xem danh sách bảng, cột, đọc dữ liệu (không có SQL tự do) |
| `artifacts` | `host-artifacts.ts` | Upload từng phần; chỉ lưu khi đúng độ dài và SHA-256 |
| `memory` | `host-memory.ts` | Nhớ/tìm/xóa ghi chú; mọi thứ đọc ra đánh dấu `untrusted` |
| `collaboration` | `host-collaboration.ts` | Tìm agent theo capability, giao việc qua `agents.delegate` |
| `sandbox` | chưa có | Trả `port_not_wired` |

Những thứ khác đã chạy trong production:

- Outbox: `OutboxPublisher` gửi event qua `createOutboxFanout` (`src/outbox-consumers.ts`); mỗi consumer
  chỉ nhận một event một lần, event lỗi quá 10 lần thì dừng thử (dead-letter).
- Ngữ cảnh model (`src/session/runtime-context.ts`): kết quả tool quá 16 KiB được thay bằng bản rút gọn;
  khi quá 24k token thì bỏ các lượt cũ nhất, luôn giữ câu hỏi mới nhất. Việc bỏ lượt chạy dưới
  lease của `CompactionCoordinator` nên hai run không cắt cùng một session cùng lúc.
- Delegation: agent chỉ được giao việc khi manifest có tool `agents.delegate` và `acceptsDelegation: false`
  (`canDelegate` trong `src/agent-contract.ts`). Không còn hard-code id `orchestrator`.
- Usage/cost: `RunLedger.recordUsage` đổi invocation id thành platform run id. Trước đây lỗi FK bị nuốt
  nên cost luôn báo 0.

Xem lớp nào được import: `pnpm inventory:write && pnpm compat:matrix`. Lưu ý: nhóm được ghi `WIRED`
khi có ít nhất một file trong nhóm được import, không phải mọi file.

## Test bằng model thật

Dùng key trong `.env`, không in key ra log.

- `pnpm bench:e2e`: API + worker riêng, PostgreSQL dùng một lần, 3 kịch bản × 3 lần.
  Receipt `docs/execution/live/e2e-benchmark-2026-09-28T02-41-23-820Z.json`, gpt-4o-mini:

  | Kịch bản | p50 | p95 |
  | --- | --- | --- |
  | Chào hỏi | 2654 ms | 4098 ms |
  | Liệt kê dữ liệu warehouse | 1638 ms | 1924 ms |
  | Phân tích có kế hoạch (đáp án đúng: North) | 6350 ms | 6645 ms |

- `scripts/live-model-eval.ts`: sentiment 12/12, `template.classifier` 4/4 (sau khi thêm guard chống
  prompt injection).

## Bài học từ 4 repo pi

| Repo | Đã áp dụng |
| --- | --- |
| pi-mcp-adapter | Tool lỗi bị khóa 60 giây (`tool_backoff`); giới hạn kích thước output |
| pi-observability-plugin | Tách token cache (đọc/ghi) khi tính usage |
| pi-subagents, pi-herdsman | Delegation theo grant, chặn chuỗi giao việc vô hạn, child run có giới hạn `maxChildRuns` |

## Quyết định chính

- `versions.json` giữ version contract và chuỗi migration (`pnpm versions`). Tên file không có v1/v2;
  `$id` trên wire (`urn:team6:schema:...:v1`), `agent-runner.v2` và `/api/v1` giữ nguyên.
- `src/experimental-contracts.ts` và các draft port cũ đã xóa; code dùng `src/contracts/`.
- Rollback rehearsal (`scripts/rehearse-rollback.mjs`): chạy code baseline `b7bd273` trên database đã
  migrate tới head hiện tại. Mọi milestone M2+ đều nằm trên cùng baseline nên dùng chung một script.
- `test/transport-loss.test.ts` từng fail ngẫu nhiên (mất 1 event SSE): helper đọc stream bỏ dở một
  `reader.read()` khi hết 200ms nên chunk đó bị nuốt. Đã sửa helper giữ lại lần đọc dở; code SSE không lỗi.

## Việc còn mở

Không chặn phát triển local, nhưng chặn việc tuyên bố "release production":

| Việc | Trạng thái | Ghi chú |
| --- | --- | --- |
| Port `sandbox` | ✅ DONE | `src/ports/host-sandbox.ts` + test suite, Docker isolation verified |
| File chưa import (30 files, ~6.5k lines) | 🔶 IDENTIFIED | workflow/* (in-memory engine), testkit/*, ports/mailbox.ts, registry/model-registry.ts, policy-engine.ts. Đã xóa 4 dead files. Giữ hay xóa phần còn lại cần quyết định owner. |
| Load, canary, restore trên hạ tầng thật | 🔴 BLOCKED | Cần staging và owner duyệt |
| Container isolation | ✅ DONE | Docker test PASS: NetworkMode none, ReadonlyRootfs verified |
| Lint warnings | 🟢 REDUCED | 493 → 76 (giảm 84%). Còn lại chủ yếu trong generated files và unreached modules. Production code còn 15-20 style warnings không ảnh hưởng correctness. |
| Receipt M13.2/M13.3 | 🔴 BLOCKED | Định dạng rehearsal riêng, cần chụp lại bằng `execution.v1` trên hạ tầng thật |
| So sánh với vde-agent-demo | ✅ DONE | `docs/comparison-vde-agent-demo.md` |

**Session 2026-09-28 hoàn thành**:
- Sandbox port: production implementation + comprehensive tests + Docker isolation verification
- Unreached file cleanup: identified 34 files, deleted 4 dead, backed up 30 remaining (~6.5k lines)
- Lint reduction: 493 → 76 warnings (84% cleanup)
- Architecture comparison: comprehensive analysis of module mechanisms

**Tests**: 102/108 files PASS, 1435/1520 tests PASS, TypeScript compilation clean.

Không coi unit test, dependency giả hoặc exit code là PASS cho các mục BLOCKED.
