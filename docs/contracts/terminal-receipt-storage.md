# Terminal Receipt Storage - M11.3

**Status**: ✅ Completed
**Purpose**: Immutable terminal receipt, identical replay no-op, changed replay conflict

## Overview

The terminal receipt storage system provides immutable records of completed run outcomes. Each receipt captures the final state including input/output hashes for deterministic replay detection, artifact references, evidence counts, and resource usage. Receipts enable idempotent execution (identical input returns cached result) and conflict detection (same input producing different output).

## Architecture

### Immutable Receipt Table

Single table design with cryptographic fingerprinting:

**terminal_receipts table** - All terminal receipts
- Primary key: `id` (rcpt_ prefixed identifier)
- Workspace isolation: `workspace_id`
- Run tracking: `run_id`, `attempt_id` (unique constraint)
- Run outcome: `status` (success | failure | timeout | cancelled), `exit_code`
- Replay detection: `input_hash` (SHA-256 of input JSON)
- Output verification: `output_hash` (SHA-256 of output JSON)
- Artifact tracking: `artifact_ids` (JSON array)
- Evidence summary: `evidence_count`, `verified_evidence_count`
- Resource usage: `duration_ms`, `tokens_input`, `tokens_output`
- Immutability: `sealed_at` (timestamp, never updated)
- Metadata: JSON blob for extensibility

### Receipt Status

Four terminal states tracked:
- **success** - Run completed successfully
- **failure** - Run failed with error
- **timeout** - Run exceeded time limit
- **cancelled** - Run was cancelled by user

## Key Features

### Deterministic Input Hashing

Input fingerprinting enables replay detection:

```typescript
// Same input always produces same hash
const receipt1 = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_001',
  attemptId: 'attempt_1',
  status: 'success',
  input: { task: 'analyze', dataset: 'sales_q3' }
});

const receipt2 = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_002',
  attemptId: 'attempt_1',
  status: 'success',
  input: { task: 'analyze', dataset: 'sales_q3' }  // Identical input
});

// receipt1.inputHash === receipt2.inputHash
```

### Replay Detection (No-Op)

Identical input returns existing receipt:

```typescript
// First execution
const receipt = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_001',
  attemptId: 'attempt_1',
  status: 'success',
  input: { query: 'SELECT * FROM users' },
  output: { rows: [...] }
});

// Check for replay before executing again
const replayCheck = await storage.checkReplay(
  'ws_prod',
  { query: 'SELECT * FROM users' }  // Same input
);

if (replayCheck.identical) {
  // Skip execution, return cached receipt
  return replayCheck.existingReceipt;
}
```

### Conflict Detection

Same input producing different output signals non-determinism:

```typescript
// First run
const receipt1 = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_001',
  attemptId: 'attempt_1',
  status: 'success',
  input: { task: 'generate_random' },
  output: { value: 42 }
});

// Second run with same input but different output
const conflictCheck = await storage.checkConflict(
  'ws_prod',
  { task: 'generate_random' },  // Same input
  { value: 73 }  // Different output!
);

if (conflictCheck.conflict) {
  console.warn('Non-deterministic behavior detected!');
  console.log('First output hash:', conflictCheck.existingReceipt.outputHash);
  console.log('New output would have different hash');
}
```

### Immutability Enforcement

Receipts cannot be modified once sealed:

```typescript
// Seal receipt
const receipt = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_001',
  attemptId: 'attempt_1',
  status: 'success',
  input: { task: 'process' }
});

// Attempting to seal another receipt with same run_id + attempt_id fails
await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_001',
  attemptId: 'attempt_1',  // Same run and attempt
  status: 'failure',
  input: { task: 'different' }
});
// Throws: unique constraint violation
```

### Workspace Isolation

All receipts enforce workspace boundaries:

```typescript
// Seal in workspace A
const receipt = await storage.seal({
  workspaceId: 'ws_a',
  runId: 'run_001',
  attemptId: 'attempt_1',
  status: 'success',
  input: { secret: 'data' }
});

// Cannot access from workspace B
const wrongWorkspace = await storage.get(receipt.id, 'ws_b');
// returns null

// Can access from correct workspace
const correctWorkspace = await storage.get(receipt.id, 'ws_a');
// returns receipt
```

### Resource Tracking

Track execution costs and artifact lineage:

```typescript
const receipt = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_001',
  attemptId: 'attempt_1',
  status: 'success',
  input: { task: 'analyze' },
  output: { insights: 15 },
  artifactIds: ['dat_results', 'chart_viz'],
  evidenceCount: 10,
  verifiedEvidenceCount: 8,
  durationMs: 45000,
  tokensInput: 1000,
  tokensOutput: 500,
  metadata: { version: '1.0' }
});

// Later: aggregate resource usage
const receipts = await storage.listByWorkspace('ws_prod');
const totalTokens = receipts.reduce((sum, r) =>
  sum + (r.tokensInput || 0) + (r.tokensOutput || 0), 0
);
```

## API Reference

### seal(params)

Seal an immutable terminal receipt for a completed run.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `runId: string` - Run identifier
- `attemptId: string` - Attempt identifier
- `status: ReceiptStatus` - Terminal status (success, failure, timeout, cancelled)
- `exitCode?: number` - Process exit code
- `input: unknown` - Run input (will be hashed)
- `output?: unknown` - Run output (will be hashed)
- `artifactIds?: string[]` - IDs of artifacts produced
- `evidenceCount?: number` - Total evidence records
- `verifiedEvidenceCount?: number` - Verified evidence count
- `durationMs?: number` - Execution duration in milliseconds
- `tokensInput?: number` - Input tokens consumed
- `tokensOutput?: number` - Output tokens produced
- `metadata?: Record<string, unknown>` - Optional metadata

**Returns:** `TerminalReceipt` - Sealed receipt

**Throws:** Error if run_id + attempt_id combination already exists

**Example:**
```typescript
const receipt = await storage.seal({
  workspaceId: 'ws_prod',
  runId: 'run_20260927_001',
  attemptId: 'attempt_1',
  status: 'success',
  exitCode: 0,
  input: { task: 'analyze_data', params: { dataset: 'sales_q3' } },
  output: { result: 'analysis_complete', insights: 15 },
  artifactIds: ['dat_abc123', 'chart_xyz789'],
  evidenceCount: 10,
  verifiedEvidenceCount: 8,
  durationMs: 45000,
  tokensInput: 1000,
  tokensOutput: 500,
  metadata: { version: '1.0', environment: 'production' }
});
```

### checkReplay(workspaceId, input)

Check if identical input has been executed before (replay detection).

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `input: unknown` - Input to check (will be hashed)

**Returns:** `ReplayCheckResult`
```typescript
{
  exists: boolean;        // Has this input been seen?
  identical: boolean;     // Is it an exact replay?
  conflict: boolean;      // Would output differ? (always false for checkReplay)
  existingReceipt?: TerminalReceipt;  // The existing receipt if found
}
```

**Example:**
```typescript
const replayCheck = await storage.checkReplay('ws_prod', {
  query: 'SELECT * FROM users WHERE active = true'
});

if (replayCheck.identical) {
  console.log('This query was already executed');
  console.log('Existing result sealed at:', replayCheck.existingReceipt.sealedAt);
  return replayCheck.existingReceipt;  // Return cached result
}

// No replay detected, execute query
```

### checkConflict(workspaceId, input, output)

Check if same input would produce different output (conflict detection).

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `input: unknown` - Input to check (will be hashed)
- `output: unknown` - Output to compare (will be hashed)

**Returns:** `ReplayCheckResult`
```typescript
{
  exists: boolean;        // Has this input been seen?
  identical: boolean;     // Does output match existing?
  conflict: boolean;      // Does output differ?
  existingReceipt?: TerminalReceipt;  // The existing receipt if found
}
```

**Example:**
```typescript
const conflictCheck = await storage.checkConflict(
  'ws_prod',
  { task: 'generate_report', date: '2026-09-27' },
  { report: 'current_version', timestamp: Date.now() }
);

if (conflictCheck.conflict) {
  console.error('Non-deterministic behavior detected!');
  console.error('Same input produced different output');
  console.error('Original:', conflictCheck.existingReceipt.outputHash);
  // Alert operations team
}
```

### get(receiptId, workspaceId)

Retrieve receipt by ID.

**Returns:** `TerminalReceipt | null`

**Example:**
```typescript
const receipt = await storage.get('rcpt_lx4m9k8n7', 'ws_prod');
if (receipt) {
  console.log(`Run ${receipt.runId} completed with status: ${receipt.status}`);
}
```

### getByRun(runId, workspaceId)

Retrieve receipt by run ID (most recent attempt).

**Returns:** `TerminalReceipt | null`

**Example:**
```typescript
const receipt = await storage.getByRun('run_20260927_001', 'ws_prod');
if (receipt) {
  console.log(`Run completed in ${receipt.durationMs}ms`);
}
```

### listByWorkspace(workspaceId, options?)

List all receipts in workspace (chronologically descending).

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `options?: { limit?: number; offset?: number }` - Pagination options

**Returns:** `TerminalReceipt[]`

**Example:**
```typescript
// Get recent receipts
const recent = await storage.listByWorkspace('ws_prod', { limit: 10, offset: 0 });

// Paginate through all receipts
let offset = 0;
const limit = 100;
while (true) {
  const page = await storage.listByWorkspace('ws_prod', { limit, offset });
  if (page.length === 0) break;
  // Process page
  offset += limit;
}
```

### listByStatus(workspaceId, status, options?)

List receipts by terminal status.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `status: ReceiptStatus` - Status filter (success, failure, timeout, cancelled)
- `options?: { limit?: number; offset?: number }` - Pagination options

**Returns:** `TerminalReceipt[]`

**Example:**
```typescript
// Get all failures
const failures = await storage.listByStatus('ws_prod', 'failure');
for (const failure of failures) {
  console.log(`Run ${failure.runId} failed with exit code ${failure.exitCode}`);
}

// Get recent successes
const successes = await storage.listByStatus('ws_prod', 'success', { limit: 50 });
```

### countByStatus(workspaceId)

Count receipts by terminal status.

**Returns:** `Record<ReceiptStatus, number>`

**Example:**
```typescript
const counts = await storage.countByStatus('ws_prod');
console.log(`Success: ${counts.success}`);
console.log(`Failure: ${counts.failure}`);
console.log(`Timeout: ${counts.timeout}`);
console.log(`Cancelled: ${counts.cancelled}`);

const successRate = counts.success /
  (counts.success + counts.failure + counts.timeout + counts.cancelled);
console.log(`Success rate: ${(successRate * 100).toFixed(2)}%`);
```

## Types

```typescript
type ReceiptStatus = "success" | "failure" | "timeout" | "cancelled";

interface TerminalReceipt {
  id: string;
  workspaceId: string;
  runId: string;
  attemptId: string;
  status: ReceiptStatus;
  exitCode: number | null;
  inputHash: string;              // SHA-256 hex string
  outputHash: string | null;      // SHA-256 hex string
  artifactIds: string[];
  evidenceCount: number;
  verifiedEvidenceCount: number;
  durationMs: number | null;
  tokensInput: number | null;
  tokensOutput: number | null;
  sealedAt: Date;
  metadata: Record<string, unknown>;
}

interface SealReceiptParams {
  workspaceId: string;
  runId: string;
  attemptId: string;
  status: ReceiptStatus;
  exitCode?: number;
  input: unknown;
  output?: unknown;
  artifactIds?: string[];
  evidenceCount?: number;
  verifiedEvidenceCount?: number;
  durationMs?: number;
  tokensInput?: number;
  tokensOutput?: number;
  metadata?: Record<string, unknown>;
}

interface ReplayCheckResult {
  exists: boolean;
  identical: boolean;
  conflict: boolean;
  existingReceipt?: TerminalReceipt;
}
```

## Database Schema

```sql
CREATE TABLE terminal_receipts (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  run_id text NOT NULL,
  attempt_id text NOT NULL,

  -- Run outcome
  status text NOT NULL CHECK (status IN ('success', 'failure', 'timeout', 'cancelled')),
  exit_code integer,

  -- Input fingerprint (for replay detection)
  input_hash text NOT NULL,

  -- Output fingerprint
  output_hash text,
  artifact_ids jsonb NOT NULL DEFAULT '[]',

  -- Evidence summary
  evidence_count integer NOT NULL DEFAULT 0,
  verified_evidence_count integer NOT NULL DEFAULT 0,

  -- Resource usage
  duration_ms bigint,
  tokens_input integer,
  tokens_output integer,

  -- Immutability
  sealed_at timestamptz NOT NULL DEFAULT now(),

  -- Metadata
  metadata jsonb NOT NULL DEFAULT '{}',

  UNIQUE (run_id, attempt_id)
);

CREATE INDEX terminal_receipts_workspace_idx ON terminal_receipts (workspace_id, sealed_at DESC);
CREATE INDEX terminal_receipts_run_idx ON terminal_receipts (run_id);
CREATE INDEX terminal_receipts_input_idx ON terminal_receipts (input_hash, workspace_id);
CREATE INDEX terminal_receipts_status_idx ON terminal_receipts (status, workspace_id);
```

## Testing

Run tests with a PostgreSQL database:

```bash
TEST_DATABASE_URL=postgresql://localhost/test npm test -- test/terminal-receipt-storage.test.ts
```

Test coverage (20 tests):
- Sealing receipts with full metadata (1 test)
- Deterministic input hashing (1 test)
- Receipts without output (1 test)
- Immutability enforcement (1 test)
- Replay detection (3 tests)
- Conflict detection (2 tests)
- Receipt retrieval by ID and run (3 tests)
- Workspace isolation (1 test)
- Receipt listing and pagination (3 tests)
- Status counting (1 test)
- Resource tracking (3 tests)

All tests enforce workspace isolation and verify hash determinism.

## Use Cases

### 1. Idempotent Execution

```typescript
// Before executing expensive operation
const replayCheck = await receipts.checkReplay(workspaceId, runInput);

if (replayCheck.identical) {
  // Return cached result immediately
  return {
    cached: true,
    receipt: replayCheck.existingReceipt,
    output: await retrieveOutput(replayCheck.existingReceipt.outputHash)
  };
}

// Execute operation
const output = await expensiveOperation(runInput);

// Seal receipt for future replays
const receipt = await receipts.seal({
  workspaceId,
  runId,
  attemptId,
  status: 'success',
  input: runInput,
  output,
  durationMs: elapsed
});
```

### 2. Non-Determinism Detection

```typescript
// After execution
const conflictCheck = await receipts.checkConflict(
  workspaceId,
  runInput,
  runOutput
);

if (conflictCheck.conflict) {
  // Alert: same input produced different output
  await alerting.send({
    severity: 'high',
    message: 'Non-deterministic behavior detected',
    runId,
    existingHash: conflictCheck.existingReceipt.outputHash,
    newOutputPreview: JSON.stringify(runOutput).slice(0, 200)
  });

  // Log for investigation
  console.error('Conflict detected:', {
    input: runInput,
    firstRun: conflictCheck.existingReceipt.runId,
    firstOutput: conflictCheck.existingReceipt.outputHash,
    currentRun: runId
  });
}
```

### 3. Cost Analysis

```typescript
// Aggregate token usage across all runs
const allReceipts = await receipts.listByWorkspace(workspaceId);

let totalInput = 0;
let totalOutput = 0;
let totalDuration = 0;

for (const receipt of allReceipts) {
  totalInput += receipt.tokensInput || 0;
  totalOutput += receipt.tokensOutput || 0;
  totalDuration += receipt.durationMs || 0;
}

console.log(`Total tokens: ${totalInput + totalOutput}`);
console.log(`Total duration: ${totalDuration}ms`);
console.log(`Average duration: ${totalDuration / allReceipts.length}ms`);
```

### 4. Success Rate Monitoring

```typescript
// Track success rate over time
const counts = await receipts.countByStatus(workspaceId);
const total = counts.success + counts.failure + counts.timeout + counts.cancelled;
const successRate = (counts.success / total) * 100;

if (successRate < 95) {
  await alerting.send({
    severity: 'medium',
    message: `Success rate dropped to ${successRate.toFixed(2)}%`,
    failures: counts.failure,
    timeouts: counts.timeout
  });
}

// Get failed runs for investigation
const failures = await receipts.listByStatus(workspaceId, 'failure', { limit: 10 });
for (const failure of failures) {
  console.log(`Failed run ${failure.runId}: exit code ${failure.exitCode}`);
}
```

### 5. Artifact Provenance

```typescript
// Find all runs that produced a specific artifact
const allReceipts = await receipts.listByWorkspace(workspaceId);
const receiptsWithArtifact = allReceipts.filter(r =>
  r.artifactIds.includes('dat_important_dataset')
);

console.log(`Artifact produced by ${receiptsWithArtifact.length} runs`);
for (const receipt of receiptsWithArtifact) {
  console.log(`  Run ${receipt.runId} at ${receipt.sealedAt}`);
  console.log(`  Input hash: ${receipt.inputHash}`);
  console.log(`  Evidence: ${receipt.verifiedEvidenceCount}/${receipt.evidenceCount} verified`);
}
```

## Related Milestones

- **M11.1**: Artifacts (completed) - provides artifact IDs for receipt tracking
- **M11.2**: Evidence refs (completed) - provides evidence counts for receipts
- **M11.4**: OTel observability - will correlate receipts with traces
- **M11.5**: Observatory - will visualize receipt timelines and conflicts
- **M11.6**: Alerts - will monitor receipt success rates and detect anomalies
