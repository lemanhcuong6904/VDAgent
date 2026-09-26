# Security boundary

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

- API không mount Docker socket; worker nội bộ mới có control path.
- Sandbox chạy non-root, network none, read-only rootfs, dropped capabilities, CPU/RAM/PID/output/
  timeout limits và workspace theo `(space, user, agent)`.
- `SandboxSupervisor` giới hạn concurrent commands và timeout; provider khác có thể thay Docker.
- Agent process nhận scope/capability grants, không nhận database/provider/Docker secret.

Audit events lưu authorization denial, rate-limit denial và operator/MCP auth failure trong
`platform_audit_events`; metadata nhạy cảm được redact. Logs/metrics không dùng raw user, space,
prompt, query result, token hoặc memory làm label.
