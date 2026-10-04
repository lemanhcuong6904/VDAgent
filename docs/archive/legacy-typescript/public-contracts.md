# Public contracts

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../README.md).

Status (2026-09-28): production runs both the legacy `AgentPlugin` roster and `agent.v1` modules.
Modules get their ports from `src/ports/host-factory.ts`; every port except `sandbox` is wired.
Open items: [PROGRESS](PROGRESS.md#việc-còn-mở); what production imports: `pnpm compat:matrix`.
Decisions: [ADR 0003](decisions/0003-public-contracts.md),
[ADR 0004](decisions/0004-reconcile-contract-prototypes.md),
[ADR 0005](decisions/0005-port-wire-contracts.md).

Import the new vocabulary from `src/contracts/index.ts`. This barrel contains generated
schemas and TypeScript types only; no database, Pi, MCP or environment access. Agents use the Python SDK in `sdk/python/`.

Gate commands: `pnpm contracts:check`, `pnpm schema:check`, `pnpm boundary:check`, `pnpm test`.
The AST boundary checker (`scripts/check-boundaries.mjs`) inspects imports, re-exports, import
types and ambient authority; legacy exceptions are exact, fingerprinted debts in
`scripts/policy/import-exceptions.json`.

## AgentModule

`AgentModule.execute` receives one `AgentExecutionContext` with input, host-owned scope, ports,
signal, deadline and `emit`/`checkpoint`/`wait` hooks. `src/contracts/module.ts` and
`src/contracts/ports.ts` are the exact API reference; the old draft vocabulary is removed and
registry, workflow and M6 port prototypes import this barrel. Port calls take `CallOptions` (signal plus absolute deadline);
identity is host-bound, never an agent-supplied option. Authoring steps: [agent-authoring](agent-authoring.md).

## Legacy bridge

`LegacyAgentAdapter` (`src/ports/legacy-bridge.ts`) wraps an existing `AgentPlugin` with its
canonical `AgentManifest` and a host-supplied `LegacyContextFactory`; it calls `plugin.run`, checks
schema, scope, JSON bounds, cancellation and deadline. Zero usage counters are synthetic and
empty evidence arrays do not prove absence of effects. Regression:
`pnpm exec vitest run test/contract/legacy-bridge.test.ts`.

## Registry

`src/registry/agent-registry.ts` pins versions and activation state (`pending/canary/enabled/disabled`);
`policy-engine.ts` intersects capabilities and grants; `catalog-adapter.ts` exposes capability
routing. Tests: `test/registry/`.

Canonical schemas are in `schemas/*.schema.json` (version trong `$id` và `versions.json`); run `pnpm contracts:generate` after
editing a public schema and `pnpm contracts:check` to detect stale generated declarations.
Runtime validation remains necessary: TypeScript cannot encode byte limits, ranges,
patterns or authentication. Generation rejects unsupported structural schema keywords.

Current types: AgentScope, StructuredError, UsageSummary, ArtifactRef, EvidenceRef,
CheckpointRef, WaitRequest, AgentEvent, ExecutionLimits, AgentResultWire.
Scope identity must come from the host. Fence is a decimal string, avoiding JS number
precision loss. Cost is explicitly estimated USD. Artifact `ready` needs SHA-256/length;
`unknown` and `pending` cannot substitute empty bytes for missing content. Evidence refs
carry classification; a `verified` flag is not itself authorization or proof.

Checkpoint references require nullable parent/base lineage, scope, fence, state hash/length
and UTC creation time. Wait requests require a reason-specific correlation key and expiry.
The host remains responsible for authorization, deadline checks and durable wakeups.

Python callers use `agent_platform.contracts.schema(name)` for fresh reference schemas.
Canonical JSON is copied byte-for-byte into package resources; generation, Python parity
and wheel smoke checks cover drift and packaging. This API is not a Python validator.

`ports.ts` now defines in-process Model/Tool/Warehouse/Artifact/Memory/Collaboration
and optional Sandbox ports. Calls carry deadline/cancellation; identity remains host-bound.

Production providers (one file each, all thin wrappers over pool tools, so the agent needs the
matching `toolGrants`):

| Port | Provider | Needs tool grants |
| --- | --- | --- |
| tools | `src/ports/host-tools.ts` | the tool itself |
| warehouse | `src/ports/host-warehouse.ts` | `warehouse.list_sources`, `list_tables`, `describe_table`, `run_query` |
| artifacts | `src/ports/host-artifacts.ts` | `artifacts.store`, `artifacts.read` |
| memory | `src/ports/host-memory.ts` | `memory.search`, `memory.remember`, `memory.forget` |
| collaboration | `src/ports/host-collaboration.ts` | `agents.delegate` |
| sandbox | none yet | returns `port_not_wired` |

Port outcomes preserve denied/failed/unknown/queued/approval/input states. Artifact
publication uses begin/write/commit, memory writes require CAS, and warehouse takes a
registered query ID rather than SQL. These method types are not runtime validation.

`module.ts` defines the in-process AgentModule/AgentExecutionContext using generated
manifest/result shapes. Completed results require output; waiting results carry a
correlated wait request and cannot simultaneously return completed output. Context identity
is readonly in TypeScript; runtime immutability and authorization remain host obligations.
The code-only fixture executes without accessing any host service.

Manifest and port data shapes are generated from canonical schemas. Workflow metadata
remains outstanding. Legacy runtime paths remain unchanged; wire/runtime integration and
full conformance are still M1/M2 work in progress, so this is not a completed SDK.

Testkit foundation: `src/testkit/call.ts` provides ManualClock and runFakeCall. It
rejects expired/cancelled calls before dispatch, aborts in-flight work, keeps interrupted
writes unknown, ignores late completion, caps JSON output bytes and removes timers.
It is a test helper, not a production policy/effect runner. Seven fake services and
wire validation now build on it; production scope/lease checks remain host obligations.

`src/testkit/tools.ts` adds a scoped fake ToolPort with explicit grants, bounded input
and execution count, exact-request idempotency, concurrent deduplication and replay of
unknown outcomes. Handler input and returned outcomes are copied; scope is frozen.
The first invocation owns cancellation/deadline for a shared execution; duplicate
waiters have their own waiting deadline/cancellation without interrupting that execution.
This is not a durable effect ledger, schema validator or complete authorization model.

AgentResult is generated from a canonical union; domain JSON maps are bounded by key
length and property count. Recursive depth and total bytes remain host-enforced limits.

Test-double JSON input/output now uses a strict bounded encoder: total UTF-8 bytes,
maximum depth 64, finite numbers, dense arrays and plain data objects. Accessors,
custom serialization, cycles and unsupported values are rejected rather than coerced.
This protects test semantics; it is not a sandbox for hostile JavaScript proxies.

AgentManifest now has a canonical schema and generated declaration. It validates the
manifest envelope and bounds embedded schema documents; it does not compile those
schemas or authorize capabilities. Workflow metadata is now canonical in agent-manifest.v1; executable
workflow graph semantics remain an M5 contract. Legacy
registry/activation behavior remains unchanged.

`src/testkit/model.ts` supplies scripted ModelPort responses with profile allowlisting,
input/output bounds, strict offline output-schema compilation and validation, bounded
call count, concurrent deduplication and deterministic provider request IDs. Usage counters
are explicitly synthetic; no provider is contacted and no production billing is claimed.

`src/testkit/warehouse.ts` provides isolated static catalog/describe/query fixtures with
registered query IDs, explicit truncation and bounded bytes/rows. Raw SQL and unknown
fields/IDs are denied. Static fixtures reject nonempty parameters explicitly; they do
not model a parameterized provider or production tenant authorization.

Warehouse fixtures can now register handlers by existing query ID, with a strict offline
parameter schema. Parameters are validated and copied before dispatch; handlers receive
cancellation and their full result is byte-bounded before row truncation. Static fixtures
continue to reject nonempty parameters.

The remaining local test doubles are now available directly from `src/testkit/`:

- `collaboration.ts`: a host-selected catalog of agent versions and outcomes, bounded
  child reservations, canonical idempotency and a `before` fault hook. `wait` reports
  completed fixtures; it is not a durable scheduler or a blocking wakeup implementation.
- `memory.ts`: one factory instance per authorized host scope/audience, allowlisted
  memory scopes/sensitivities, optimistic CAS, bounded revision history and tombstones.
  All content stays `untrusted`. Search uses a deterministic substring match and an
  ISO UTC millisecond `asOf` cutoff, not semantic retrieval. Expiry removes content
  even from historical reads; forgetting removes every revision. Replay caches store
  identities and hashes only, so expired/deleted content cannot be recovered by replay.
  Re-creating a tombstoned ID requires its current revision. Item slots include tombstones;
  mutation limits include rejected dispatched operations, bounding all retained state.
- `artifacts.ts`: isolated begin/write/commit uploads, aggregate byte reservations,
  sequential offset checks, chunk snapshots and SHA-256 verification over stored bytes.
  Missing, pending and hash-mismatched artifacts never produce successful empty reads.
  Verified zero-byte artifacts do. `maxArtifactBytes` bounds raw content; request/response
  JSON caps also account for the internal base64 representation used by the test double.
- `sandbox.ts`: schema-validated command fixtures and allowlisted artifact/credential
  references. Pause requires a running fixture; resume creates a fresh execution identity
  while retaining source lineage. Output bytes are bounded before returning status, and
  a process exit never becomes evidence. No real shell, network, vault or container is used.

Memory/artifact `before(operation, signal)` and sandbox/collaboration hooks support
faults or deferred promises driven by `ManualClock`. Deadline/cancellation after a write
starts returns `unknown`; a late hook resolution cannot apply a new mutation. Idempotent
replay retains that unknown outcome instead of relaunching. Each replay caller can stop
waiting at its own deadline without cancelling the original operation. Fault errors are
redacted. These doubles enforce local fixture boundaries, not production authentication,
lease/fence checks, crash recovery or durable receipts. The fake-call helper validates
JSON at runtime, including outputs represented by ordinary TypeScript interfaces.


Canonical `port-call.v1` and `port-result.v1` now cover all twenty port methods.
The envelope contains method/callId correlation and an absolute UTC millisecond deadline;
identity is bound separately by the host. `ports.ts` derives method input/output and
non-success outcomes from generated types. `unknown` requires a nonretryable unknown
error. Artifact `bytesBase64` replaces Uint8Array only on wire. Cancellation is a separate
transport control, not a JSON AbortSignal. See [ADR 0005](decisions/0005-port-wire-contracts.md).

`createPortWireCodec` from `src/testkit/port-wire.ts` validates standalone offline schemas,
aggregate UTF-8 bytes/depth, canonical base64 and response correlation. Defaults cap
frames at 16 MiB/depth 64; tighter limits can be injected. Schema validation alone checks
base64 character vocabulary; the codec also checks padding and canonical pad bits.
The codec does not authorize calls, compile embedded domain schemas, dispatch effects,
verify evidence or connect process transports. Tests exercise output from all seven
fake ports across all twenty methods, including artifact byte conversion.

Generate/check only these schemas with `node scripts/generate-contracts.mjs --schema=port-call.schema.json --schema=port-result.schema.json [--check]`.
This scoped command prints its limited scope and does not replace the full generation
or schema gate. The existing `agent-protocol.schema.json` draft currently fails the
repository canonical schema conventions and full generator; that M9 integration debt
must be resolved before claiming a complete gate.


Workflow metadata is now an optional `workflow` property of `agent-manifest.v1`.
It is closed and bounded: workflow identity/version, display/description, state/output
schemas, capabilities, required ports, tags and host limits (`maxNodes`, `maxDepth`,
`maxFanOut`, duration/cost and approval). This metadata declares compatibility and policy
inputs; it does not authorize activation or make a planner proposal executable. The
handwritten `src/workflow/workflow-module.ts` still owns executable plan/node semantics
until M5 defines their canonical wire schema.
