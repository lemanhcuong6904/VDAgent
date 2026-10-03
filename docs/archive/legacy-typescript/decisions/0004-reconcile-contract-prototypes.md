# ADR 0004 — Reconcile incompatible prototypes

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

Status: implemented locally; human review pending. Scope: M1/M2 foundation repair.

The public contract barrel must export declarations generated from the existing
canonical schemas (ADR 0003), not a second handwritten vocabulary with incompatible
scope, artifact and port semantics. No wire schema/version change is introduced.
Existing draft declarations were first preserved in `src/experimental-contracts.ts`.
Update 2026-09-27: that module and its five draft port adapters (superseded by
`src/ports/host-factory.ts` and the testkit fakes) are deleted; registry, workflow and M6
prototypes now import `src/contracts/index.ts` and use the canonical 12-field `AgentScope`.
These prototypes are not production SDK implementations and must not be activated as such.

Restore the existing PostgreSQL RunLedger API required by the server and durable
worker. Preserve the Map-backed draft as `workflow/in-memory-run-ledger.ts` and test
it independently. No migration or persisted application data is changed.

The new legacy bridge calls AgentPlugin.run with an explicitly supplied private host
context. It checks identity, schemas, bounded JSON, cancellation and deadlines.
It does not collect usage/evidence or stop non-cooperative side effects; synthetic
zero counters carry an explicit warning. Host authorization remains required.
createPorts assembles already bound canonical ports; it does not create providers.

Compatibility: existing production routes retain the legacy execution path; Python
runner remains agent-runner.v1. Testkit and new contract tests use canonical types.
Trade-off (resolved by the update above): the duplicate draft vocabulary stayed temporarily to
preserve ongoing work, isolated explicitly rather than silently changing public contracts.

Verification: typecheck, canonical generation/parity, contract and bridge tests,
AST boundaries, existing backend suite and disposable PostgreSQL integration tests.
Passing prototype tests does not complete M1–M7 or approve deployment.

Rollback: revert these local source/test changes as a reviewed patch; no database
rollback is needed. Do not restore the Map ledger at the production import path.
