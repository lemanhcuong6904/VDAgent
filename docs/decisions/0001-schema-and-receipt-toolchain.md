# ADR 0001 — Versioned schemas và execution evidence

Status: implemented for M0 tooling; public agent runtime contracts unchanged.
Owner: Platform/agent runtime + Build/release/platform. Human reviewer: pending.

## Requirement và quyết định

M0.2–M0.4 yêu cầu JSON Schema là source of truth, validation deterministic và receipt
không biến skipped test/claim thành proof. Dùng JSON Schema Draft 2020-12 cho schema
mới tại `schemas/`; Ajv 8.20.0 và ajv-formats 3.0.1 là dev dependency pin chính xác,
được khai báo trực tiếp thay vì phụ thuộc package transitively từ MCP.

Ajv strict mode compile schema local, không load remote reference, không coercion,
default injection hoặc remove unknown fields. Nguồn kiểm chứng: README và declarations
của package Ajv/ajv-formats đã cài trong lockfile. Web documentation không truy cập được
trong phiên này; không dùng lỗi truy cập để suy ra khả năng của package.

Schema receipt dùng ID `urn:team6:schema:execution-receipt:v1` và payload discriminator
`execution.v1`. Validator thứ hai kiểm timestamp ordering, command status, test counts,
rollback references, SHA-256/byte length và bounded filesystem paths.

## Consumers và compatibility

- `scripts/capture-baseline.mjs` tạo receipt gate mới và log theo ID capture duy nhất.
- `scripts/validate-receipt.mjs` validate offline; exit 0 chỉ xác nhận receipt hợp lệ,
  kể cả receipt có status FAIL/NOT_RUN. Không xác nhận milestone hoặc release.
- `scripts/check-schemas.mjs` compile tất cả schema và kiểm conventions.
- `scripts/tests/` có Node test runner riêng; không đụng behavior backend/SDK/frontend.
- `baseline.v1` cũ (`M0-baseline.json`, đã xóa 2026-09-27) là historical capture
  chưa chuẩn hóa. Giữ nguyên bằng chứng, không rewrite thành receipt đã được verify.
  CLI mới reject version cũ; bản capture mới dùng execution.v1.

Input hashes mô tả checkout lúc chạy; lịch sử có thể khác checkout hiện tại. Evidence
logs/artifacts phải luôn khớp hash. `--current-inputs` bổ sung kiểm input với checkout
hiện tại để phát hiện sửa source sau khi chạy gate.

## Trade-offs, validation và rollback

Receipt dùng JSON Schema cộng semantic validator vì schema không thể tự đọc artifact
hoặc xác nhận thứ tự thời gian. Reviewer field là record do operator khai báo, không
phải chữ ký hay cơ chế authorization. Milestone PASS bắt buộc reviewer và rollback
command evidence, nhưng human review vẫn phải kiểm phạm vi test và GIT_RULE.md.

Tests kiểm invalid timestamp/version/unknown field/bounds, hash substitution, traversal,
symlink escape, missing evidence, skipped/failed tests và fake rollback reference.
Chạy `corepack pnpm schema:check` và `corepack pnpm governance:test`.

Rollback: revert tooling/schema/scripts/package dev dependency changes; không migration
DB hoặc runtime path nào thay đổi. Giữ receipt/log cũ để đối chiếu. Chưa diễn tập rollback.

M0.2 pin frontend/runtime/container/database và M0.6 supply chain gates còn đang làm;
ADR này không tuyên bố chúng đã hoàn thành.
