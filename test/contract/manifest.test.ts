import { Ajv2020 } from "ajv/dist/2020.js";
import { expect, it } from "vitest";
import { AgentManifestSchema } from "../../src/contracts/index.js";

const validate = new Ajv2020({ strict: true }).compile(AgentManifestSchema);
const manifest = {
  apiVersion: "agent.v1",
  id: "example.double",
  version: "1.0.0",
  displayName: "Double",
  inputSchema: {
    type: "object",
    properties: { value: { type: "number" } },
    required: ["value"],
    additionalProperties: false,
  },
  outputSchema: true,
  capabilities: ["math.double"],
  requiredPorts: [],
  toolGrants: [],
  limits: {
    timeoutMs: 100,
    maxInputBytes: 128,
    maxOutputBytes: 128,
    maxEventBytes: 128,
    maxCheckpointBytes: 128,
    maxModelCalls: 0,
    maxToolCalls: 0,
    maxChildRuns: 0,
    maxDepth: 0,
    maxCostUsd: 0,
  },
  compatibility: { minHostVersion: "1.0.0" },
};
it("accepts a code-only manifest with embedded schema documents", () => {
  expect(validate(manifest)).toBe(true);
  expect(validate({ ...manifest, inputSchema: false })).toBe(true);
});
it("rejects unknown authority, unsupported ports and malformed grant/version/budget fields", () => {
  for (const change of [
    { apiVersion: "agent.v2" },
    { version: "latest" },
    { requiredPorts: ["database"] },
    { credentials: "inline" },
    { inputSchema: [] },
    { toolGrants: [{ toolId: "tool", version: "1.0.0", effect: "shell" }] },
    { limits: { ...manifest.limits, maxDepth: -1 } },
  ])
    expect(validate({ ...manifest, ...change })).toBe(false);
});

it("validates bounded workflow metadata inside an agent manifest", () => {
  const manifest = {
    apiVersion: "agent.v1",
    id: "agent",
    version: "1.0.0",
    displayName: "Agent",
    inputSchema: { type: "object" },
    outputSchema: { type: "string" },
    capabilities: ["analyze"],
    requiredPorts: ["model"],
    toolGrants: [],
    limits: {
      timeoutMs: 1000,
      maxInputBytes: 1024,
      maxOutputBytes: 1024,
      maxEventBytes: 1024,
      maxCheckpointBytes: 1024,
      maxModelCalls: 1,
      maxToolCalls: 1,
      maxChildRuns: 1,
      maxDepth: 1,
      maxCostUsd: 1,
    },
    compatibility: { minHostVersion: "1.0.0" },
    workflow: {
      apiVersion: "workflow.v1",
      id: "workflow",
      version: "1.0.0",
      displayName: "Workflow",
      description: "bounded workflow",
      stateSchema: { type: "object" },
      outputSchema: { type: "string" },
      capabilities: ["analyze"],
      requiredPorts: ["model"],
      limits: {
        maxNodes: 4,
        maxDepth: 4,
        maxFanOut: 2,
        maxDurationMs: 1000,
        maxCostUsd: 1,
        requiresApproval: false,
      },
    },
  };
  expect(validate(manifest)).toBe(true);
  expect(
    validate({
      ...manifest,
      workflow: { ...manifest.workflow, limits: { ...manifest.workflow.limits, maxDepth: 0 } },
    }),
  ).toBe(false);
  expect(validate({ ...manifest, workflow: { ...manifest.workflow, privateHost: true } })).toBe(
    false,
  );
});
