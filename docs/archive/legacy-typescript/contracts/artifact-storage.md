# Artifact Storage - M11.1

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Status**: ✅ Completed
**Purpose**: Metadata-first artifact publication with SHA-256/length readback and owner/isolation/version tracking

## Overview

The artifact storage system provides content-addressable storage with cryptographic verification. Every artifact is published metadata-first, ensuring integrity tracking from creation through verification.

## Architecture

### Two-Table Design

**artifacts table** - Metadata and status tracking
- Primary key: `id` (kind-prefixed identifier)
- Workspace isolation: `workspace_id`
- Ownership tracking: `owner_run_id`
- Version tracking: `version` (semver string)
- Status: `pending` → `ready` | `failed`
- Integrity: `sha256` hash, `bytes` size
- Metadata: JSON blob for extensibility

**artifact_contents table** - Binary storage
- One-to-one with artifacts (CASCADE delete)
- Content stored as `bytea`
- Separate for performance (metadata queries don't load blobs)

### Publication Flow

```typescript
// 1. Compute hash and size upfront
const sha256 = computeSha256(content);
const bytes = content.length;

// 2. Insert metadata (status: pending)
await db.insert('artifacts', {
  id, workspaceId, ownerRunId, kind, version,
  status: 'pending', sha256, bytes, metadata
});

// 3. Store content
await db.insert('artifact_contents', { artifactId: id, content });

// 4. Mark ready (atomic state transition)
await db.update('artifacts', { status: 'ready', readyAt: now() });

// 5. Return hash and size for verification
return { id, sha256, bytes };
```

## Key Features

### SHA-256 Verification

Every artifact can be verified by hash:

```typescript
const result = await storage.store({ content, ... });
// result.sha256 is the canonical hash

// Later verification
const isValid = await storage.verify({
  id: artifactId,
  sha256: expectedHash
});
// true only if status=ready AND hash matches
```

### Workspace Isolation

Artifacts are isolated by workspace:

```typescript
// Store in workspace A
await storage.store({ workspaceId: 'ws_a', ... });

// Cannot access from workspace B
const metadata = await storage.getMetadata(id, 'ws_b');
// returns null

// Access from correct workspace
const metadata = await storage.getMetadata(id, 'ws_a');
// returns full metadata
```

### Version Tracking

Multiple versions can coexist:

```typescript
const v1 = await storage.store({
  kind: 'dataset',
  version: '1.0.0',
  content: Buffer.from('Version 1')
});

const v2 = await storage.store({
  kind: 'dataset',
  version: '2.0.0',
  content: Buffer.from('Version 2')
});

// Both v1.id and v2.id are distinct artifacts
```

### Owner Run Tracking

Each artifact records its creating run:

```typescript
await storage.store({
  ownerRunId: 'run_abc123',
  ...
});

// List all artifacts from a run
const artifacts = await storage.listByOwnerRun('run_abc123');
```

## API Reference

### store(params)

Store artifact with metadata-first publication.

**Parameters:**
- `workspaceId: string` - Workspace identifier
- `ownerRunId: string` - Creating run identifier
- `kind: string` - Artifact type (dataset, chart, report, etc.)
- `version: string` - Version string (default: "1.0.0")
- `content: Buffer` - Binary content
- `metadata?: Record<string, unknown>` - Optional metadata

**Returns:** `{ id: string, sha256: string, bytes: number }`

**Example:**
```typescript
const result = await storage.store({
  workspaceId: 'ws_prod',
  ownerRunId: 'run_20260927_001',
  kind: 'dataset',
  version: '1.2.0',
  content: Buffer.from(JSON.stringify(data)),
  metadata: { name: 'Q3 Sales', source: 'warehouse' }
});
```

### verify(params)

Verify artifact integrity by SHA-256.

**Parameters:**
- `id: string` - Artifact identifier
- `sha256: string` - Expected hash (64 hex chars)

**Returns:** `boolean` - True if artifact is ready and hash matches

**Example:**
```typescript
const isValid = await storage.verify({
  id: 'dat_abc123',
  sha256: result.sha256
});
```

### getMetadata(id, workspaceId)

Retrieve artifact metadata.

**Returns:** `ArtifactMetadata | null`

**Example:**
```typescript
const metadata = await storage.getMetadata('dat_abc123', 'ws_prod');
// {
//   id, workspaceId, ownerRunId, kind, version,
//   status, sha256, bytes, metadata,
//   createdAt, readyAt
// }
```

### getContent(id, workspaceId)

Retrieve artifact content (enforces workspace isolation).

**Returns:** `Buffer | null`

**Example:**
```typescript
const content = await storage.getContent('dat_abc123', 'ws_prod');
```

### listByWorkspace(workspaceId, options?)

List artifacts in a workspace.

**Options:**
- `limit?: number` - Max results (default 100)
- `offset?: number` - Pagination offset (default 0)

**Returns:** `ArtifactMetadata[]` (ordered by creation DESC)

### listByOwnerRun(ownerRunId)

List all artifacts created by a run.

**Returns:** `ArtifactMetadata[]` (ordered by creation ASC)

### markReady(id)

Mark pending artifact as ready (for streaming uploads).

**Example:**
```typescript
// Store metadata first
const { id } = await storage.store({
  ...params,
  content: Buffer.from('') // Empty placeholder
});

// Stream content in chunks...

// Mark ready when complete
await storage.markReady(id);
```

## Error Handling

### Storage Failure

If content storage fails, artifact status is marked as `failed`:

```typescript
try {
  await storage.store({ ... });
} catch (error) {
  // Artifact row exists with status='failed'
  // Content row does not exist
}
```

### Verification Failure

Verification returns `false` for:
- Non-existent artifact
- Status not `ready` (pending or failed)
- Hash mismatch

```typescript
const isValid = await storage.verify({ id, sha256 });
if (!isValid) {
  // Either: artifact not found, not ready, or hash wrong
  // Check metadata to determine cause
  const metadata = await storage.getMetadata(id, workspaceId);
  if (!metadata) {
    // Artifact does not exist
  } else if (metadata.status !== 'ready') {
    // Artifact not ready yet
  } else {
    // Hash mismatch - integrity violation
  }
}
```

## Database Schema

```sql
CREATE TABLE artifacts (
  id text PRIMARY KEY,
  workspace_id text NOT NULL,
  owner_run_id text NOT NULL,
  kind text NOT NULL,
  version text NOT NULL DEFAULT '1.0.0',
  status text NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
  sha256 text,
  bytes bigint,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  ready_at timestamptz
);

CREATE TABLE artifact_contents (
  artifact_id text PRIMARY KEY REFERENCES artifacts(id) ON DELETE CASCADE,
  content bytea NOT NULL,
  stored_at timestamptz NOT NULL DEFAULT now()
);
```

## Testing

Run tests with a PostgreSQL database:

```bash
TEST_DATABASE_URL=postgresql://localhost/test npm test -- test/artifact-storage.test.ts
```

Test coverage:
- Metadata-first publication (4 tests)
- SHA-256 verification (4 tests)
- Metadata retrieval (2 tests)
- Content retrieval (3 tests)
- Workspace/run listing (3 tests)
- Version tracking (1 test)

All tests enforce workspace isolation and verify status transitions.

## Migration Path

Existing systems (web_datasets, web_charts, web_reports) remain unchanged. New agents can adopt artifact storage:

```typescript
// Old way (specific tables)
await db.query(
  'INSERT INTO web_datasets (id, user_id, ...) VALUES (...)'
);

// New way (unified storage)
const result = await artifactStorage.store({
  workspaceId: userId,
  ownerRunId: runId,
  kind: 'dataset',
  version: '1.0.0',
  content: Buffer.from(JSON.stringify(dataset))
});
```

## Related Milestones

- **M11.2**: Evidence refs will link artifacts via their immutable IDs
- **M11.3**: Terminal receipts will include artifact SHA-256 hashes
- **M11.4**: OTel spans will track artifact publication latency
- **M11.5**: Observatory will visualize artifact dependencies
