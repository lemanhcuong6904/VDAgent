import { describe, expect, it } from "vitest";
import type { RunGraphNodeDTO, RunViewDTO } from "../api/types";
import { costRows, formatBytes, formatCost, formatMs, orderGraph, outcomeLabel } from "./runView";

function node(id: string): RunGraphNodeDTO {
  return {
    id,
    kind: "agent",
    agentId: null,
    capability: null,
    status: "completed",
    attempt: 0,
    startedAt: null,
    finishedAt: null,
    durationMs: null,
  };
}

function view(overrides: Partial<RunViewDTO> = {}): RunViewDTO {
  return {
    run: {
      id: "run_1",
      workflowId: "analytics",
      workflowVersion: "1.0.0",
      status: "completed",
      createdAt: "2026-09-27T12:00:00Z",
      updatedAt: "2026-09-27T12:00:00Z",
      finishedAt: "2026-09-27T12:00:05Z",
      durationMs: 5000,
      terminal: true,
      cancelRequested: false,
    },
    graph: { nodes: [], edges: [], roots: [] },
    approvals: [],
    artifacts: [],
    evidence: {
      counts: { verified: 0, unverified: 0, unavailable: 0 },
      items: [],
      truncated: false,
    },
    cost: {
      totals: { records: 0, inputTokens: 0, outputTokens: 0, latencyMs: 0, estimatedCost: 0 },
      byModel: {},
      byAgent: {},
    },
    errors: [],
    receipt: null,
    permissions: { canCancel: false, canDecideApproval: false },
    truncated: false,
    ...overrides,
  };
}

describe("orderGraph", () => {
  it("walks roots breadth-first with depth", () => {
    const result = orderGraph({
      nodes: [node("c"), node("b"), node("a")],
      edges: [
        { from: "a", to: "b" },
        { from: "b", to: "c" },
      ],
      roots: ["a"],
    });
    expect(result.map(({ node: entry, depth }) => `${entry.id}:${depth}`)).toEqual([
      "a:0",
      "b:1",
      "c:2",
    ]);
  });

  it("keeps unreachable nodes and survives a cycle", () => {
    const result = orderGraph({
      nodes: [node("a"), node("b"), node("orphan")],
      edges: [
        { from: "a", to: "b" },
        { from: "b", to: "a" },
      ],
      roots: ["a"],
    });
    expect(result.map(({ node: entry }) => entry.id)).toEqual(["a", "b", "orphan"]);
  });

  it("ignores edges and roots naming unknown nodes", () => {
    const result = orderGraph({
      nodes: [node("a")],
      edges: [{ from: "a", to: "ghost" }],
      roots: ["ghost", "a"],
    });
    expect(result.map(({ node: entry }) => entry.id)).toEqual(["a"]);
  });
});

describe("formatters", () => {
  it("formats cost, bytes and durations", () => {
    expect(formatCost(0.1234)).toBe("$0.1234");
    expect(formatCost(2)).toBe("$2.00");
    expect(formatCost(Number.NaN)).toBe("—");
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatMs(450)).toBe("450ms");
    expect(formatMs(65_000)).toBe("1m 05s");
    expect(formatMs(null)).toBe("");
  });

  it("sorts cost rows most expensive first", () => {
    const totals = (estimatedCost: number) => ({
      records: 1,
      inputTokens: 0,
      outputTokens: 0,
      latencyMs: 0,
      estimatedCost,
    });
    expect(
      costRows({ cheap: totals(0.01), dear: totals(1), mid: totals(0.5) }).map((row) => row.key),
    ).toEqual(["dear", "mid", "cheap"]);
  });
});

describe("outcomeLabel", () => {
  it("claims success only from a sealed success receipt", () => {
    const sealed = view({
      receipt: {
        status: "success",
        sealedAt: "2026-09-27T12:00:05Z",
        evidenceCount: 3,
        verifiedEvidenceCount: 2,
        durationMs: 5000,
      },
    });
    expect(outcomeLabel(sealed)).toEqual({
      text: "Receipt sealed: success · 2/3 evidence verified",
      tone: "ok",
    });
  });

  it("does not infer success from a completed status without a receipt", () => {
    const label = outcomeLabel(view());
    expect(label.tone).toBe("warn");
    expect(label.text).toContain("no receipt");
    expect(label.text).not.toMatch(/success/);
  });

  it("reports a sealed failure as an error", () => {
    const failed = view({
      receipt: {
        status: "timeout",
        sealedAt: "2026-09-27T12:00:05Z",
        evidenceCount: 0,
        verifiedEvidenceCount: 0,
        durationMs: null,
      },
    });
    expect(outcomeLabel(failed).tone).toBe("error");
  });
});
