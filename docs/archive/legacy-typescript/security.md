# Security boundary

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

Platform coi prompt, model output, memory, tool result và warehouse data là untrusted input.
Authorization được thực hiện tại API, `McpToolPool`, warehouse/artifact scope và agent communication;
system prompt không phải security boundary.

Web routes hỗ trợ session bearer token. Demo mode chỉ dành cho local development và cho phép
`X-User-Id`; không bật mode này khi public. Operator `/v1` luôn cần `API_TOKEN`; MCP luôn cần
`AGENT_TOKEN_<ID>` và `X-Agent-Id`. So sánh agent token constant-time và secure mode từ chối
placeholder.

HTTP có body limit, secure headers, configured CORS và bounded per-process rate limiter. Multi-replica
deployment phải đặt rate limiter phân tán ở gateway hoặc thay implementation bằng store dùng chung;
rate limiter process-local chỉ là defense-in-depth.

Worker/sandbox boundary:

- Production Compose không mount Docker socket và đặt `SANDBOX_PROVIDER=none`; quyền vào socket tương
  đương quyền quản trị Docker trên host. Deployment riêng chỉ bật Docker sandbox khi có supervisor tin cậy.
- Sandbox chạy non-root, network none, read-only rootfs, dropped capabilities, CPU/RAM/PID/output/
  timeout limits và workspace theo `(space, user, agent)`.
- `SandboxSupervisor` giới hạn concurrent commands và timeout; provider khác có thể thay Docker.
- Agent process nhận scope/capability grants, không nhận database/provider/Docker secret.

Delegation: agent chỉ được giao việc cho agent khác khi manifest có tool `agents.delegate` và
`acceptsDelegation: false` (`canDelegate` trong `src/agent-contract.ts`). Registry từ chối agent vừa
giao việc vừa nhận việc, nên không thể tạo chuỗi giao việc vô hạn.

Contract stack mới giữ cùng nguyên tắc (một số file chưa được production import, xem
[PROGRESS](PROGRESS.md#việc-còn-mở)):
`src/registry/policy-engine.ts` giao capability/grant và pin policy revision; `src/sandbox-policy.ts`
kiểm resource/egress/filesystem và chỉ nhận credential reference, từ chối inline secret;
`src/agent-runner.ts` authorize từng `port_call`, kiểm sequence/correlation và schema protocol không phải
authorization. A2A gateway và `/api/v1` đã nối production, có security negatives ở
[contracts/security-negatives](contracts/security-negatives.md). Scan dependency, SBOM, image pin và
secret rotation: [runbooks/security-scan](runbooks/security-scan.md).

Audit events lưu authorization denial, rate-limit denial và operator/MCP auth failure trong
`platform_audit_events`; metadata nhạy cảm được redact. Logs/metrics không dùng raw user, space,
prompt, query result, token hoặc memory làm label.
