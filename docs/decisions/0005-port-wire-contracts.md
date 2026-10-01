# ADR 0005 — Port call/result wire v1

Status: implementation in progress. Scope: M1.2/M1.4/M1.6. Owner: Platform/contracts.

The seven in-process ports have twenty methods but no canonical serializable request
or response vocabulary. Add `port-call.v1` and `port-result.v1` schemas, generated
TypeScript declarations and byte-identical Python reference resources. Existing
agent-runner.v1/v2 drafts and production adapters do not switch protocols in this change.

Each closed envelope carries `apiVersion`, `callId`, `method` and either `input` plus
`deadline` or `outcome`. Method is a discriminant, so a warehouse call cannot carry tool
arguments and a result cannot use a different method's successful output shape.
Deadline is an integer UTC epoch millisecond value; the host clamps it to the run budget.
Call ID correlates transport messages, while mutation idempotency keys remain inside
method input. Identity, actor, tenant, grants, fence and credential values are never
caller-selected envelope fields. The host binds them through the authenticated run.
Cancellation remains a transport control message correlated to callId, not a JSON signal.

Artifact bytes use canonical padded RFC 4648 base64 (`bytesBase64`) on wire and
Uint8Array locally. Control objects reject unknown fields. Arbitrary domain JSON and
embedded schema documents are explicitly bounded exceptions, consistent with ADR 0003.
The whole encoded payload must additionally pass a byte/depth cap before schema
validation; per-field JSON Schema constraints do not prevent nested aggregate growth.
The default hard ceiling is 16 MiB and depth 64; callers may only tighten these limits.
Base64 validation rejects nonzero padding bits before decoding; empty bytes remain valid
only where the artifact lifecycle allows them. SHA-256/ownership verification belongs
to ArtifactPort, not the transport codec.

All outcome states remain explicit: ok, queued, needs_approval, needs_input, denied,
failed, unknown. Unknown requires error.class=unknown and retryable=false; transport
uncertainty cannot authorize automatic replay. A schema-valid evidence ref does not
establish verified evidence. Result correlation must match both method and callId.

Port signatures derive their data types from generated schemas, with explicit local
substitutions for AbortSignal and Uint8Array. This makes drift a compile error instead
of maintaining another independent set of handwritten wire declarations. A testkit
codec validates bounded JSON, schema, base64 and correlation; it is not a dispatcher
or an authorization layer. Shared vocabulary definitions are copied locally to keep
schemas standalone/offline; parity tests fail if copies drift from canonical sources.

Validation: positive fixtures for every method/result, all non-success states,
unknown-field/identity/version/method/correlation negatives, size/depth/base64 checks,
compile-time equality of local/generated types and Python schema resource parity.
No claims of process transport compatibility, host policy integration or production
execution until the corresponding M2/M9 gates pass.

Rollback: remove the new schema/generated/testkit surfaces and restore in-process type
aliases. No database, runtime feature flag, route or deployed protocol migration.

Implementation note: the schema constrains base64 characters/length using a linear
character-class pattern; codec canonical re-encoding verifies quartet/padding rules.
This avoids repeated-group regular-expression stack exhaustion for large byte chunks.
The generator supports explicit `--schema=<canonical filename>` selection for incremental
checks and rejects unknown/receipt selections. No-selection still processes every schema
and continues to fail on incompatible existing protocol drafts; it is not an exclusion list.

Workflow metadata is intentionally separate from port envelopes. A manifest may declare
a workflow, while plan nodes, edges, retry/compensation and checkpoint semantics remain
the M5 workflow contract. This prevents a schema declaration from silently becoming an
executable graph.
