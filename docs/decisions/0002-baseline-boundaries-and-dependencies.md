# ADR 0002 — M0 inventory, boundaries và dependency baseline

Owner: Platform/build và Platform/agent runtime. Human review pending.
Không đổi public runtime contract hoặc DB migration.

## Scope

Inventory dùng TypeScript AST để liệt kê exports/imports/registration call sites và
test declarations, cộng lexical SQL CREATE TABLE và Python top-level declarations.
`inventory:check` fail khi source khác bản snapshot. Test declaration không chứng minh
coverage; integration tests và receipt là bằng chứng runtime riêng.

Import gate áp dụng `src/agents/`, `src/agent-sdk.ts`, `src/contracts/`. Module chỉ
import public contracts/SDK, TypeBox và helper cùng thư mục agent. Public barrels cũng
bị kiểm; dynamic import không xác định và ambient process/network/eval bị reject.
Resolver fail khi tsconfig thêm alias/extends chưa review; kiểm canonical symlink target.
Đây là static architecture gate, không phải sandbox chống malicious JavaScript.

17 dependency/authority edges legacy được ghi rõ trong `scripts/policy/import-exceptions.json`.
Mỗi exception có file, rule, chi tiết, statement hash, owner và mốc gỡ M2/M10.
Không cho wildcard; vi phạm trùng thêm hoặc exception stale làm gate fail. Giữ các
edge này để không đổi behavior M0; không tuyên bố target dependency direction đã đạt.

Secret scan offline chỉ dùng high-confidence token/private-key/credential-URL patterns,
không echo match; không đọc ignored `.env`. `.env` nếu tracked là violation không mở file.
Scan cả untracked nonignored text; không scan history/binary. Giới hạn này không thay
secret scanning production M13. Placeholder `.env.example` được nhận dạng hẹp.

## Versions và licenses

Local Node 24.18.0 trong `.node-version`; container Node 24.21.0 được pin bằng digest
của image local đang có. Không đổi engines support range vì chưa có matrix chứng minh
thu hẹp support. pnpm 9.15.0, frontend npm 12.0.2; TS backend 5.9.3, frontend 7.0.2.
Frontend direct dependencies pin đúng phiên bản lock hiện tại, không upgrade. PostgreSQL
17.10 pin digest trùng disposable test harness. Dockerfile/Compose chưa được rebuild ở
thay đổi này; full image reproducibility (apt/Python build tooling) còn M13.

Protocol hiện tại: `agent-runner.v1`; descriptor legacy `agent-plugin.v1|v2`.
`agent.v1` là contract đích M1, chưa tự thay protocol v1 bridge.

Dependency gate kiểm exact versions, manifest-lock parity, SHA-512 integrity và license
expression drift cho cả hai Node lockfiles. BOM repository-native liệt kê component và
dependency edges; không giả định là SPDX/CycloneDX. Backend npm sbom không đọc đúng pnpm
layout nên không dùng output lỗi làm proof. Frontend npm sbom được thử riêng nhưng chưa
được coi là release artifact. OS/Python SBOM và live CVE scanning còn M13.

License metadata lấy từ installed package/pnpm licenses, frontend lock và npm registry
cho platform-specific package thiếu local. Registry record phải khớp name/version và
integrity trong lock; network refresh là lệnh riêng, gate offline không tự sửa policy.
MPL-2.0 hiện có được ghi nhận; metadata gate không phải legal/distribution approval.

## Rollback

Revert scripts/policy, manifests/lock metadata và image references về bản trước; không
chạm data migration. Chưa có rollback rehearsal/reviewer nên M0 vẫn đang triển khai.
