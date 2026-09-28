# Runbook: security scan và image pinning (M13.5)

## Lỗ hổng dependency

`pnpm audit` (backend) và `npm audit` (frontend) chạy gate mỗi lần dependency thay đổi. Kết quả
hiện tại (2026-09-27): **0 critical, 0 high, 0 moderate, 0 low**. Receipts `audit-backend.json` /
`audit-frontend.json` ghi từng run. Không có scanner CVE độc lập (Trivy, Grype, OSV-Scanner); chỉ
dựa vào registry của npm/pnpm.

## SBOM và license

`dependency:check` sinh `docs/execution/dependency-bom.json` (623 component, 1166 relationship,
định dạng repo native chứ không phải SPDX/CycloneDX). `scripts/policy/licenses.json` là allowlist;
`scripts/policy/registry-license-metadata.json` bổ sung metadata của những package thiếu trường
license (chỉ dùng nếu integrity khớp). Gate PASS mỗi lần lockfile thay đổi.

## Image pinning

- `node@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6` (frontend + runtime)
- `postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`
- `otel/opentelemetry-collector-contrib:0.123.0`, `prom/prometheus:v3.2.1`, `grafana/grafana:11.5.2`

Base image (node/postgres) dùng SHA256 digest, không thay đổi khi registry publish bản vá (cần
update thủ công). Observability stack dùng tag semantic; có thể chuyển sang digest nếu cần immutable.

## Secret rotation

`API_TOKEN` và `AGENT_TOKEN_*` được sinh từ `openssl rand -base64 48` và lưu trong `.env`, không
commit. Rotation: sinh token mới → ghi vào `.env` → restart API (worker tự động lấy env mới) → xóa
token cũ khỏi client. Database password nằm trong `DATABASE_URL`, rotation yêu cầu rolling restart
với grace period > `WORKER_DRAIN_GRACE_MS`.

## Chưa làm

- **Trivy/Grype/OSV-Scanner**: scanner độc lập so với npm/pnpm registry, quét CVE từ NVD/GitHub
  Advisory. Cần CI integration hoặc pre-commit hook.
- **Egress review**: worker mount Docker socket và có outbound internet (model API, tool webhook).
  Chưa có allowlist hay network policy.
- **Sandbox escape test**: container non-root + read-only rootfs + no-new-privileges + dropped caps,
  nhưng chưa có red-team hoặc chaos drill.
