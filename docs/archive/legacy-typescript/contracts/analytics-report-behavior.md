# Report Generation Behavior Contract

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Module ID**: `analytics.report`
**Version**: 1.0.0
**Status**: Active

## Purpose

Assembles structured markdown reports from specialist outputs (comparison, insight, visualization). Persists complete reports to the warehouse for user consumption and sharing.

## Contract

### Input Schema
- `prompt` (string, required): User request for report (1-4000 chars)
- `datasetId` (string, required): Dataset identifier matching `ds_[a-zA-Z0-9]{12}` or a deterministic 24-character lowercase hex ID
- `chartId` (string, required): Chart identifier matching `ch_[a-zA-Z0-9]{12}`
- `compareContext` (string, optional): Context from comparison step (max 2000 chars)
- `insightContext` (string, optional): Context from insight step (max 2000 chars)
- `visualizeContext` (string, optional): Context from visualization step (max 2000 chars)

### Output Schema
- `reportId` (string, optional): Persisted report ID matching `rp_[a-zA-Z0-9]{12}`
- `error` (string, optional): Error message if report generation failed

### Capabilities
- `warehouse:query` - Query datasets and charts for report assembly
- `warehouse:report` - Persist reports to warehouse
- `model:completion` - Report structuring and prose generation
- `report:generate` - Markdown report assembly

### Required Ports
- `warehouse` - Data warehouse connection
- `model` - Model inference for report generation

### Limits
- Timeout: 60s (longest of all behaviors)
- Max model calls: 4
- Max tool calls: 10
- Max input: 32KB (largest input due to multiple contexts)
- Max output: 8KB
- Max cost: $0.50

## Evidence

### Verification Criteria
1. **Report Persistence**: Successful output must contain valid `reportId` matching pattern
2. **Context Integration**: Must assemble all three specialist contexts (compare, insight, visualize)
3. **Markdown Structure**: Report must be well-formed markdown with sections
4. **Artifact References**: Must embed datasetId and chartId in report content
5. **Fallback Behavior**: When model fails, `createFallbackReport()` assembles from specialist outputs

### Detection Pattern
Report generation triggered when user prompt contains:
```typescript
/\b(?:report|chart|visuali[sz]e|save|write-up)\b|báo cáo|biểu đồ|lưu lại/i
```

### Fallback Strategy
When model-based report generation fails:
1. Extract datasetId and chartId from prompt
2. Parse specialist results from compareContext, insightContext, visualizeContext
3. Assemble markdown sections:
   - Title from prompt
   - Data Summary section with datasetId
   - Comparison Findings section from compareContext
   - Insights section from insightContext
   - Visualization section with chartId
4. Persist assembled markdown to warehouse
5. Return reportId

### Test Coverage
- `test/analytics-e2e.test.ts` / `test/parity-e2e.test.ts` - Full report workflow
- `test/web-api.test.ts` - Report persistence and retrieval

### Known Limitations
1. Requires all three upstream artifacts (datasetId, chartId, contexts)
2. Fallback report uses simple section assembly - may lack narrative flow
3. No support for multi-chart reports
4. Report styling controlled by warehouse render layer, not customizable here
5. Vietnamese report generation depends on model's multilingual capability
6. 32KB input limit may truncate long specialist outputs

### Dependencies
- Upstream: All other analytics behaviors (data, compare, insight, visualize)
- Downstream: None (terminal behavior in analytics pipeline)

## Migration Notes

**From**: Inline report logic in `analytics.ts`
**To**: Standalone behavior module with contract

Extracted in M10.1. Most complex behavior due to dependency on all other specialists. Implementation in `src/agents/behaviors/report.ts` with sophisticated fallback markdown assembly. Orchestrator invokes only when `needsReport()` pattern detected.

**Removal Target**: Import exceptions removed when AgentModule implementation complete.
