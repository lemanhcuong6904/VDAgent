# ADR 0003 — Public contract v1 foundation

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

Status: implementation in progress (M1). Owner: Platform/agent runtime.

JSON Schema remains source of truth. New wire schemas use versioned URNs in `schemas/`;
generated TypeScript declarations live in `src/contracts/generated/`. They must not import
host runtime, database, Pi or MCP modules. The legacy `src/agent-sdk.ts` types keep their
existing names and semantics until the M2 adapter exists.

First shared vocabulary: structured error, usage, execution scope, artifact/evidence
references. Identity is explicit, required and server-owned; a structurally valid scope
does not authenticate its caller. Usage records distinguish measured counts and estimated
cost. Evidence classification preserves claims/observer hints separately from receipts;
an evidence reference alone does not establish proof of success.

Closed control-plane objects reject unknown fields. Event/process forward compatibility
will be explicit in their own schemas; no global stripping of unknown fields. Schema
validation is separate from runtime policy, identity, CAS and evidence verification.

Type generation supports the schema subset in these contracts and fails on unsupported
structural keywords, rather than silently emitting an inaccurate type. Python reference
schemas are copied from the same canonical source and compared byte-for-byte by the
generation gate. Python resource API parity tests and wheel checks cover packaging.

Consumers in M1 are isolated contract tests only. M2 will add execution adapters. No
production routing or persistence migration in this change. Rollback removes the new
schema/generated package/test surface; old AgentPlugin/SDK paths remain operational.

The in-process port method signatures live in `src/contracts/ports.ts`. They describe
host-bound calls, not serializable wire envelopes: AbortSignal and Uint8Array remain
local API types. Per-port request/result wire schemas and protocol adapters are still
required before claiming full M1 conformance. Callers cannot supply identity in options;
warehouse queries use registered query IDs; artifact publication is begin/write/commit;
memory writes require revision/CAS and preserve untrusted classification. These types
do not replace runtime grant, scope, deadline, limit or hash checks.

Module lifecycle types are additive and provisional pending their canonical schemas:
completed requires output, waiting requires a reason-specific request, and wait() never
returns successfully to the same invocation. Agent-emitted progress/warnings cannot
mark a run terminal. Manifest/workflow integration is not claimed complete by these
handwritten types; M1 must replace data declarations with schema-generated forms.

AgentEvent and ExecutionLimits now use canonical schemas/generated declarations.
Producer events are closed progress/warning observations, not terminal ledger events;
unknown-field tolerant external event consumers remain a separate adapter requirement.
Hard contract ceilings: one-day timeout, 16 MiB payload/checkpoint limits, 10,000 model
or tool calls, 1,024 children, depth 64 and estimated USD 1,000,000. These are validation
ceilings, not default grants: the host must intersect substantially narrower policy limits.
Zero model/tool/child/cost budgets explicitly disable those effects; byte/deadline caps
must remain positive. Changing these ceilings requires a reviewed contract change.

Generator now resolves local `#/$defs/<Identifier>` to schema-prefixed TypeScript aliases,
including recursive definitions. Missing/remote references and constraint siblings on a
reference fail rather than silently losing constraints. AgentEvent evidence uses a local
Evidence definition. Canonical JSON is still copied unchanged to Python resources.

AgentResult now has a canonical discriminated union and generated wire type; the generic
in-process result only narrows completed output. Domain JSON dictionaries permit schema-
validated additional values with explicit maxProperties/property-name limits; control
objects remain closed. JSON depth and aggregate bytes still require host validation;
schema per-container limits alone do not bound recursive total size.

AgentManifest now has a canonical schema and generated TypeScript/Python reference.
Embedded input/output schemas are bounded JSON documents, not automatically valid JSON
Schema: the host must compile them, reject remote references, verify capability/grant
availability and compare host versions before activation. Workflow metadata remains
unimplemented pending the WorkflowManifest design; M1 manifest coverage is not complete
until that requirement is resolved. No registry activation behavior changes here.
