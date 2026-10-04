# Reference Agent Implementations

> **Historical — legacy TypeScript platform, no longer active.** This page describes the TypeScript/PostgreSQL
> platform (`src/`, `sdk/python`, root `package.json`) that was removed on 2026-10-04 (Phase 4; code is in Git history,
> commit `aed2917`). Paths and commands below no longer exist or run. Current system: [docs/README.md](../../../README.md).

**Status**: ✅ Completed (M10.4)
**Purpose**: Canonical patterns for teams building new agents

## Overview

Three reference implementations demonstrate the AgentModule contract:

1. **Model-Backed** (`reference.summarizer`) - Text summarization using Pi runtime
2. **Code-Only** (`reference.statistics`) - Pure computation with no external calls
3. **Workflow-Backed** (`reference.text-analyzer`) - Child agent orchestration

## Pattern 1: Model-Backed Agent

**File**: `src/agents/reference/model-backed.ts`

### When to Use
Your agent needs LLM inference capabilities for tasks like:
- Text generation or transformation
- Natural language understanding
- Content summarization or extraction
- Conversational responses

### Key Characteristics
- Declares `requiredPorts: ["model"]`
- Uses `context.ports.model.prompt()` for inference
- Sets `maxModelCalls` budget in limits
- Returns usage tracking with token counts
- Handles model errors gracefully with `status: "failed"`

### Example Structure
```typescript
export const summarizerAgent: AgentModule<Input, Output> = {
  manifest: {
    capabilities: ["text.summarize", "model.completion"],
    requiredPorts: ["model"],
    limits: {
      maxModelCalls: 1,
      maxCostUsd: 0.10,
      // ...
    },
  },

  async execute(context) {
    const response = await context.ports.model.prompt({
      messages: [...],
      maxTokens: 150,
      temperature: 0.3,
    });

    return {
      status: "completed",
      output: { summary: response },
      usage: { /* track tokens */ },
    };
  },
};
```

## Pattern 2: Code-Only Agent

**File**: `src/agents/reference/code-only.ts`

### When to Use
Your agent performs pure computation:
- Mathematical calculations
- Data transformations
- Validation or formatting
- Deterministic algorithms

### Key Characteristics
- Declares `requiredPorts: []` (no external dependencies)
- Sets `maxModelCalls: 0, maxToolCalls: 0`
- Executes synchronously or with minimal async overhead
- Zero cost: `maxCostUsd: 0.0`
- Fast timeouts: `timeoutMs: 5000` or less

### Example Structure
```typescript
export const statisticsAgent: AgentModule<Input, Output> = {
  manifest: {
    capabilities: ["math.statistics", "compute.pure"],
    requiredPorts: [],
    limits: {
      maxModelCalls: 0,
      maxToolCalls: 0,
      maxCostUsd: 0.0,
    },
  },

  async execute(context) {
    const { numbers } = context.input;
    const sorted = [...numbers].sort((a, b) => a - b);
    const mean = sorted.reduce((a, b) => a + b, 0) / sorted.length;

    return {
      status: "completed",
      output: { mean, /* ... */ },
      usage: { /* all zeros except durationMs */ },
    };
  },
};
```

## Pattern 3: Workflow-Backed Agent

**File**: `src/agents/reference/workflow-backed.ts`

### When to Use
Your agent orchestrates multiple sub-tasks:
- Multi-stage processing pipelines
- Parallel analysis across dimensions
- Delegating specialized work to child agents
- Aggregating results from multiple sources

### Key Characteristics
- Declares `requiredPorts: ["delegation"]`
- Uses `context.ports.delegation.delegate()` to spawn child runs
- Sets `maxChildRuns` and `maxDepth` limits
- Aggregates child usage costs
- Handles delegation failures gracefully

### Example Structure
```typescript
export const textAnalyzerAgent: AgentModule<Input, Output> = {
  manifest: {
    capabilities: ["text.analyze", "workflow.orchestrate"],
    requiredPorts: ["delegation"],
    limits: {
      maxChildRuns: 2,
      maxDepth: 2,
      maxCostUsd: 0.15,
    },
  },

  async execute(context) {
    const statisticsResult = computeLocally();

    const summaryResult = await context.ports.delegation.delegate({
      capability: "text.summarize",
      input: { text: context.input.text },
      maxDepth: 1,
    });

    return {
      status: "completed",
      output: { statistics, summary: summaryResult.output },
      usage: { /* aggregate costs */ },
    };
  },
};
```

## Common Patterns

### Error Handling
All three patterns handle three failure modes:
1. **Cancellation**: Check `context.signal.aborted`, return `status: "canceled"`
2. **Recoverable errors**: Return `status: "failed"` with `error.recoverable: true`
3. **Fatal errors**: Return `status: "failed"` with `error.recoverable: false`

### Usage Tracking
Return accurate usage even on failure:
```typescript
usage: {
  inputTokens: 0,
  outputTokens: 0,
  modelCalls: 0,
  toolCalls: 0,
  durationMs: Date.now() - startTime,
  estimatedCostUsd: totalCost,
}
```

### Manifest Validation
The registry validates:
- `capabilities` match regex: `^[a-z0-9][a-z0-9._-]{0,127}$`
- `apiVersion` is `"agent.v1"`
- `inputSchema` and `outputSchema` are valid JSON Schema v7
- `limits` do not exceed platform defaults

## Testing

**File**: `test/agent-runner/reference-agents.test.ts`

All three reference agents have comprehensive test coverage:
- Manifest structure validation
- Happy path execution
- Error handling
- Cancellation support
- Edge cases (empty input, delegation failures, etc.)

Run tests:
```bash
npm test -- test/agent-runner/reference-agents.test.ts
```

## Registry Integration

Reference agents can be registered like any other agent:

```typescript
import { summarizerAgent, statisticsAgent, textAnalyzerAgent } from "./agents/reference/index.js";

registry.registerModule(summarizerAgent);
registry.registerModule(statisticsAgent);
registry.registerModule(textAnalyzerAgent);
```

Once registered, they're discoverable via capability routing:
```typescript
const agent = registry.findByCapability("text.summarize");
// Returns summarizerAgent
```

## Migration Guide

Teams migrating from AgentPlugin to AgentModule can reference these patterns:

| Old Pattern | New Pattern | Reference |
|-------------|-------------|-----------|
| `context.runtime.prompt()` | `context.ports.model.prompt()` | model-backed.ts |
| Pure computation in `run()` | Same logic in `execute()` | code-only.ts |
| `context.pool.call("agents.delegate")` | `context.ports.delegation.delegate()` | workflow-backed.ts |

## Next Steps

1. Choose the pattern that matches your agent's needs
2. Copy the reference implementation as a starting point
3. Update manifest with your capabilities and limits
4. Implement your business logic in `execute()`
5. Add tests following the reference test patterns
6. Register your agent in the catalog

## Related Documentation

- [AgentModule Contract](../public-contracts.md#agentmodule)
- [Registry and capability routing](../public-contracts.md#registry)
- [Legacy bridge](../public-contracts.md#legacy-bridge)
- [M10.3: Capability Migration](../PLAN.md)
