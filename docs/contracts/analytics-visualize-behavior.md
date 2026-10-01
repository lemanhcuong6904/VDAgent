# Visualization Behavior Contract

**Module ID**: `analytics.visualize`
**Version**: 1.0.0
**Status**: Active

## Purpose

Creates charts and visual representations from prepared datasets. Selects appropriate chart types based on data characteristics and analysis context, then persists charts to the warehouse.

## Contract

### Input Schema
- `prompt` (string, required): User request for visualization (1-4000 chars)
- `datasetId` (string, required): Dataset identifier matching `ds_[a-zA-Z0-9]{12}` or a deterministic 24-character lowercase hex ID
- `compareContext` (string, optional): Context from comparison step (max 2000 chars)
- `insightContext` (string, optional): Context from insight step (max 2000 chars)

### Output Schema
- `chartId` (string, optional): Persisted chart ID matching `ch_[a-zA-Z0-9]{12}`
- `error` (string, optional): Error message if visualization failed

### Capabilities
- `warehouse:query` - Query datasets for chart dimensions
- `warehouse:chart` - Persist charts to warehouse
- `model:completion` - Chart type selection
- `visualize:create` - Chart generation

### Required Ports
- `warehouse` - Data warehouse connection
- `model` - Model inference for chart selection

### Limits
- Timeout: 45s
- Max model calls: 4
- Max tool calls: 8
- Max input: 16KB
- Max output: 8KB
- Max cost: $0.50

## Evidence

### Verification Criteria
1. **Chart Persistence**: Successful output must contain valid `chartId` matching pattern
2. **Type Selection**: Must choose appropriate chart type based on data dimensions
3. **Context Integration**: Should use compareContext and insightContext to inform visualization choices
4. **Fallback Behavior**: When model selection fails, `createFallbackVisualization()` creates default chart

### Fallback Strategy
When model-based chart creation fails:
1. Extract datasetId from prompt
2. Query dataset for available dimensions
3. Select dimensions heuristically (first text column as X, first numeric as Y)
4. Create default chart with warehouse chart API
5. Return persisted chartId

### Test Coverage
- `test/analytics-e2e.test.ts` / `test/parity-e2e.test.ts` - Visualization workflow integration
- `test/web-api.test.ts` - Chart persistence verification

### Known Limitations
1. Requires valid datasetId from data behavior
2. Fallback visualization may not choose optimal chart type
3. No support for multi-chart dashboards (single chart per invocation)
4. Chart styling and theming not customizable through contract
5. Limited to warehouse-supported chart types

### Dependencies
- Upstream: `analytics.data` (requires datasetId), `analytics.compare` and `analytics.insight` (optional context providers)
- Downstream: `analytics.report` (consumes chartId for report assembly)

## Migration Notes

**From**: Inline visualization logic in `analytics.ts`
**To**: Standalone behavior module with contract

Extracted in M10.1. Implementation includes both model-backed selection and fallback creation in `src/agents/behaviors/visualize.ts`. Orchestrator calls when report requested or explicit visualization needed.

**Removal Target**: Import exceptions removed when AgentModule implementation complete.
