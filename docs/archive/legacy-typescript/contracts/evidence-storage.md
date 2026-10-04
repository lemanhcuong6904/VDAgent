# Evidence Storage - M11.2

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Status**: ✅ Completed
**Purpose**: Evidence refs linking source/run/tool/model/artifact revision with immutable audit trail

## Overview

The evidence storage system provides an immutable audit trail for agent execution. Each evidence record links source code, tool calls, model interactions, artifact references, and checkpoints to specific runs and attempts, enabling complete reproducibility and verification.

## Architecture

### Polymorphic Evidence Table

Single table design with kind-specific columns:

**evidence_refs table** - All evidence types
- Primary key: `id` (kind-prefixed identifier)
- Workspace isolation: `workspace_id`
- Run tracking: `run_id`, `attempt_id`
- Evidence kind: `source | tool_call | model_call | artifact_ref | checkpoint`
- Verification status: `unverified | verified | unavailable`
- Kind-specific columns (nullable, populated per kind)
- Metadata: JSON blob for extensibility

### Evidence Kinds

**1. Source Evidence** - Files, git commits, external resources
```typescript
{
  kind: "source",
  sourceType: "git" | "file" | "external",
  sourceLocation: "https://github.com/org/repo.git",
  sourceRevision: "abc123def456"
}
```

**2. Tool Call Evidence** - Tool invocations with hashed I/O
```typescript
{
  kind: "tool_call",
  toolId: "warehouse.query",
  toolInputHash: "sha256(...)",  // Hash of input JSON
  toolOutputHash: "sha256(...)"  // Hash of output JSON
}
```

**3. Model Call Evidence** - LLM interactions with token counts
```typescript
{
  kind: "model_call",
  modelId: "claude-opus-4",
  modelInputHash: "sha256(...)",   // Hash of prompt
  modelOutputHash: "sha256(...)",  // Hash of completion
  modelTokens: { input: 100, output: 50, cacheRead: 20 }
}
```

**4. Artifact Reference Evidence** - Links to stored artifacts
```typescript
{
  kind: "artifact_ref",
  artifactId: "dat_abc123",
  artifactSha256: "sha256(...)"  // Links to artifact's hash
}
```

**5. Checkpoint Evidence** - Execution state snapshots
```typescript
{
  kind: "checkpoint",
  checkpointId: "ckpt_20260927_001",
  checkpointRevision: 5
}
```

## Key Features

### Hash-Based Verification

Tool and model calls use deterministic hashing:

```typescript
// Record tool call
const evidenceId = await storage.recordToolCall({
  workspaceId,
  runId,
  attemptId,
  toolId: "read_file",
  toolInput: { path: "/src/app.ts" },
  toolOutput: { content: "..." }
});

// Hash computation is automatic and deterministic
// Same input always produces same hash
```

### Verification Status Tracking

Evidence transitions through verification states:

```typescript
// Initially unverified
const id = await storage.recordSource({ workspaceId, ... });

// Verify after checking source exists
await storage.markVerified(id, workspaceId);

// Or mark unavailable if source is gone
await storage.markUnavailable(id, workspaceId);

// Count by status
const counts = await storage.countByStatus(runId, workspaceId);
// { unverified: 5, verified: 12, unavailable: 2 }
```

### Workspace Isolation

All evidence queries enforce workspace boundaries:

```typescript
// Store in workspace A
const id = await storage.recordSource({
  workspaceId: 'ws_a',
  ...
});

// Cannot access from workspace B
const evidence = await storage.get(id, 'ws_b');
// returns null

// Access from correct workspace
const evidence = await storage.get(id, 'ws_a');
// returns full evidence
```

### Complete Audit Trail

Link evidence to runs and artifacts:

```typescript
// List all evidence for a run
const runEvidence = await storage.listByRun(runId, workspaceId);
// Returns sources, tool calls, model calls, artifacts, checkpoints

// List all runs that used an artifact
const references = await storage.listByArtifact(artifactId, workspaceId);
// Returns artifact_ref evidence linking runs to artifact
```

## API Reference

### recordSource(params)

Record source evidence (file, git commit, external resource).

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `runId: string` - Run identifier
- `attemptId: string` - Attempt identifier
- `sourceType: string` - Source type (git, file, external)
- `sourceLocation: string` - Source location (URL, path)
- `sourceRevision: string` - Revision identifier (commit hash, version)
- `metadata?: Record<string, unknown>` - Optional metadata

**Returns:** `string` - Evidence ID

**Example:**
```typescript
const evidenceId = await storage.recordSource({
  workspaceId: 'ws_prod',
  runId: 'run_20260927_001',
  attemptId: 'attempt_1',
  sourceType: 'git',
  sourceLocation: 'https://github.com/org/repo.git',
  sourceRevision: 'abc123def456',
  metadata: { branch: 'main', author: 'alice' }
});
```

### recordToolCall(params)

Record tool call evidence with automatic hash computation.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `runId: string` - Run identifier
- `attemptId: string` - Attempt identifier
- `toolId: string` - Tool identifier
- `toolInput: unknown` - Tool input (will be hashed)
- `toolOutput: unknown` - Tool output (will be hashed)
- `metadata?: Record<string, unknown>` - Optional metadata

**Returns:** `string` - Evidence ID

**Example:**
```typescript
const evidenceId = await storage.recordToolCall({
  workspaceId: 'ws_prod',
  runId: 'run_20260927_001',
  attemptId: 'attempt_2',
  toolId: 'warehouse.query',
  toolInput: { query: 'SELECT * FROM users' },
  toolOutput: { rows: [{ id: 1, name: 'Alice' }] },
  metadata: { duration: 123 }
});
```

### recordModelCall(params)

Record model call evidence with token counts.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `runId: string` - Run identifier
- `attemptId: string` - Attempt identifier
- `modelId: string` - Model identifier
- `modelInput: string` - Prompt text (will be hashed)
- `modelOutput: string` - Completion text (will be hashed)
- `tokens: TokenCounts` - Token usage
- `metadata?: Record<string, unknown>` - Optional metadata

**TokenCounts:**
```typescript
{
  input: number;
  output: number;
  cacheRead?: number;
  cacheWrite?: number;
}
```

**Returns:** `string` - Evidence ID

**Example:**
```typescript
const evidenceId = await storage.recordModelCall({
  workspaceId: 'ws_prod',
  runId: 'run_20260927_001',
  attemptId: 'attempt_3',
  modelId: 'claude-opus-4',
  modelInput: 'Summarize this dataset',
  modelOutput: 'The dataset contains...',
  tokens: { input: 100, output: 50, cacheRead: 200 },
  metadata: { temperature: 0.7 }
});
```

### recordArtifactRef(params)

Record artifact reference evidence.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `runId: string` - Run identifier
- `attemptId: string` - Attempt identifier
- `artifactId: string` - Artifact identifier
- `artifactSha256: string` - Artifact SHA-256 hash
- `metadata?: Record<string, unknown>` - Optional metadata

**Returns:** `string` - Evidence ID

**Example:**
```typescript
const evidenceId = await storage.recordArtifactRef({
  workspaceId: 'ws_prod',
  runId: 'run_20260927_001',
  attemptId: 'attempt_4',
  artifactId: 'dat_abc123',
  artifactSha256: artifactResult.sha256,
  metadata: { usage: 'input_dataset' }
});
```

### recordCheckpoint(params)

Record checkpoint evidence.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `runId: string` - Run identifier
- `attemptId: string` - Attempt identifier
- `checkpointId: string` - Checkpoint identifier
- `checkpointRevision: number` - Checkpoint revision number
- `metadata?: Record<string, unknown>` - Optional metadata

**Returns:** `string` - Evidence ID

**Example:**
```typescript
const evidenceId = await storage.recordCheckpoint({
  workspaceId: 'ws_prod',
  runId: 'run_20260927_001',
  attemptId: 'attempt_5',
  checkpointId: 'ckpt_20260927_001',
  checkpointRevision: 5,
  metadata: { step: 'after_validation' }
});
```

### markVerified(evidenceId, workspaceId)

Mark evidence as verified inside its workspace. Artifact references are marked verified only when the
artifact is ready, has matching workspace metadata, and its stored bytes still match the recorded
SHA-256 digest. A missing or changed artifact is marked unavailable and the method returns `false`.

**Example:**
```typescript
await storage.markVerified(evidenceId, workspaceId);
```

### markUnavailable(evidenceId, workspaceId)

Mark evidence as unavailable (source deleted, artifact missing).

**Example:**
```typescript
await storage.markUnavailable(evidenceId, workspaceId);
```

### get(evidenceId, workspaceId)

Retrieve evidence by ID.

**Returns:** `Evidence | null`

**Example:**
```typescript
const evidence = await storage.get('src_abc123', 'ws_prod');
if (evidence.kind === 'source') {
  console.log(evidence.sourceLocation);
}
```

### listByRun(runId, workspaceId)

List all evidence for a run (ordered chronologically).

**Returns:** `Evidence[]`

**Example:**
```typescript
const evidence = await storage.listByRun('run_20260927_001', 'ws_prod');
// [source, tool_call, model_call, artifact_ref, checkpoint]
```

### listByArtifact(artifactId, workspaceId)

List all artifact reference evidence for an artifact.

**Returns:** `ArtifactRefEvidence[]`

**Example:**
```typescript
const references = await storage.listByArtifact('dat_abc123', 'ws_prod');
// All runs that used this artifact
```

### countByStatus(runId, workspaceId)

Count evidence by verification status.

**Returns:** `Record<VerificationStatus, number>`

**Example:**
```typescript
const counts = await storage.countByStatus('run_20260927_001', 'ws_prod');
// { unverified: 5, verified: 12, unavailable: 2 }
```

## Evidence Types

```typescript
type Evidence =
  | SourceEvidence
  | ToolCallEvidence
  | ModelCallEvidence
  | ArtifactRefEvidence
  | CheckpointEvidence;

interface BaseEvidence {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  kind: EvidenceKind;
  verification: VerificationStatus;
  metadata: Record<string, unknown>;
  createdAt: Date;
  verifiedAt: Date | null;
}

interface SourceEvidence extends BaseEvidence {
  kind: "source";
  sourceType: string;
  sourceLocation: string;
  sourceRevision: string;
}

interface ToolCallEvidence extends BaseEvidence {
  kind: "tool_call";
  toolId: string;
  toolInputHash: string;
  toolOutputHash: string;
}

interface ModelCallEvidence extends BaseEvidence {
  kind: "model_call";
  modelId: string;
  modelInputHash: string;
  modelOutputHash: string;
  modelTokens: {
    input: number;
    output: number;
    cacheRead?: number;
    cacheWrite?: number;
  };
}

interface ArtifactRefEvidence extends BaseEvidence {
  kind: "artifact_ref";
  artifactId: string;
  artifactSha256: string;
}

interface CheckpointEvidence extends BaseEvidence {
  kind: "checkpoint";
  checkpointId: string;
  checkpointRevision: number;
}
```

## Database Schema

```sql
CREATE TABLE evidence_refs (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  run_id text NOT NULL,
  attempt_id text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('source', 'tool_call', 'model_call', 'artifact_ref', 'checkpoint')),
  verification text NOT NULL CHECK (verification IN ('unverified', 'verified', 'unavailable')),

  -- Source evidence
  source_type text,
  source_location text,
  source_revision text,

  -- Tool call evidence
  tool_id text,
  tool_input_hash text,
  tool_output_hash text,

  -- Model call evidence
  model_id text,
  model_input_hash text,
  model_output_hash text,
  model_tokens jsonb,

  -- Artifact reference evidence
  artifact_id text,
  artifact_sha256 text,

  -- Checkpoint evidence
  checkpoint_id text,
  checkpoint_revision integer,

  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz
);

CREATE INDEX evidence_refs_workspace_idx ON evidence_refs (workspace_id, created_at DESC);
CREATE INDEX evidence_refs_run_idx ON evidence_refs (run_id, created_at ASC);
CREATE INDEX evidence_refs_artifact_idx ON evidence_refs (artifact_id) WHERE artifact_id IS NOT NULL;
CREATE INDEX evidence_refs_verification_idx ON evidence_refs (verification, kind);
```

## Testing

Run tests with a PostgreSQL database:

```bash
TEST_DATABASE_URL=postgresql://localhost/test npm test -- test/evidence-storage.test.ts
```

Test coverage (18 tests):
- Source evidence recording (1 test)
- Tool call evidence with hashing (2 tests)
- Model call evidence with tokens (1 test)
- Artifact reference evidence (2 tests)
- Checkpoint evidence (1 test)
- Verification status transitions (3 tests)
- Evidence retrieval (3 tests)
- Workspace isolation (1 test)
- Metadata storage (1 test)
- Chronological ordering (1 test)
- Status counting (1 test)

All tests enforce workspace isolation and verify hash determinism.

## Use Cases

### 1. Reproducible Runs

```typescript
// Record all evidence during run
const sourceId = await evidence.recordSource({
  workspaceId, runId, attemptId,
  sourceType: 'git',
  sourceLocation: repo,
  sourceRevision: commit
});

const toolId = await evidence.recordToolCall({
  workspaceId, runId, attemptId,
  toolId: 'read_file',
  toolInput: { path: '/src/app.ts' },
  toolOutput: { content: '...' }
});

const modelId = await evidence.recordModelCall({
  workspaceId, runId, attemptId,
  modelId: 'claude-opus-4',
  modelInput: prompt,
  modelOutput: completion,
  tokens: { input: 100, output: 50 }
});

// Later: reconstruct exact run
const allEvidence = await evidence.listByRun(runId, workspaceId);
// Replay with same sources, same inputs, same model
```

### 2. Artifact Lineage

```typescript
// Link artifact to creating run
await evidence.recordArtifactRef({
  workspaceId, runId, attemptId,
  artifactId: result.id,
  artifactSha256: result.sha256,
  metadata: { role: 'output' }
});

// Later: find all runs that created or used this artifact
const references = await evidence.listByArtifact(artifactId, workspaceId);
for (const ref of references) {
  console.log(`Run ${ref.runId} at ${ref.createdAt}`);
}
```

### 3. Verification Audits

```typescript
// Check run completeness
const counts = await evidence.countByStatus(runId, workspaceId);

if (counts.unavailable > 0) {
  console.warn('Some evidence is unavailable');
}

if (counts.unverified > 0) {
  // Verify remaining evidence
  const allEvidence = await evidence.listByRun(runId, workspaceId);
  for (const e of allEvidence.filter(e => e.verification === 'unverified')) {
    if (await checkAvailability(e)) {
      await evidence.markVerified(e.id, workspaceId);
    } else {
      await evidence.markUnavailable(e.id, workspaceId);
    }
  }
}
```

### 4. Cost Tracking

```typescript
// Sum token usage across runs
const allEvidence = await evidence.listByRun(runId, workspaceId);
const modelCalls = allEvidence.filter(e => e.kind === 'model_call');

let totalInput = 0;
let totalOutput = 0;
let totalCacheRead = 0;

for (const call of modelCalls) {
  totalInput += call.modelTokens.input;
  totalOutput += call.modelTokens.output;
  totalCacheRead += call.modelTokens.cacheRead || 0;
}

console.log(`Input: ${totalInput}, Output: ${totalOutput}, Cache: ${totalCacheRead}`);
```

## Related Milestones

- **M11.1**: Artifacts (completed) - provides artifact IDs and SHA-256 hashes
- **M11.3**: Terminal receipts - will include evidence IDs for verification
- **M11.4**: OTel observability - will correlate evidence with traces
- **M11.5**: Observatory - will visualize evidence graphs
- **M11.6**: Alerts - will detect evidence availability issues
