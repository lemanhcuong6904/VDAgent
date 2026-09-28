import { beforeEach, describe, expect, it } from "vitest";
import {
  BasicHostAuthority,
  createDefaultAuthorityPolicy,
} from "../../src/workflow/host-authority.js";
import type { PlanProposal } from "../../src/workflow/planner.js";
import type { PlanSpec } from "../../src/workflow/workflow-module.js";
import { testScope } from "../helpers/scope.js";

describe("BasicHostAuthority", () => {
  let authority: BasicHostAuthority;

  const samplePlan: PlanSpec = {
    version: "plan.v1",
    workflowId: "test-workflow",
    nodes: [
      {
        id: "node-1",
        type: "agent",
        displayName: "Test Node",
        agentId: "test-agent",
        inputSchema: {},
        outputSchema: {},
        timeout: 30000,
        retryPolicy: {
          class: "transient",
          maxAttempts: 3,
          backoffMs: 1000,
        },
        checkpointBoundary: false,
      },
    ],
    edges: [],
    budget: {
      maxCostUsd: 0.05,
      maxDurationMs: 30000,
      maxModelTokens: 10000,
      maxToolCalls: 5,
    },
  };

  const lowCostProposal: PlanProposal = {
    proposalId: "proposal-1",
    workflowId: "workflow-1",
    runId: "run-1",
    scope: testScope({ runId: "run-1" }),
    plan: samplePlan,
    rationale: "Simple test workflow",
    estimatedCost: 0.05,
    estimatedDuration: 30000,
    riskLevel: "low",
    requiresApproval: false,
    proposedAt: new Date().toISOString(),
    proposedBy: "system",
  };

  beforeEach(() => {
    const policy = createDefaultAuthorityPolicy();
    authority = new BasicHostAuthority(policy);
  });

  describe("requestApproval", () => {
    it("should create approval request", async () => {
      const request = await authority.requestApproval(lowCostProposal);

      expect(request.requestId).toBeDefined();
      expect(request.proposalId).toBe("proposal-1");
      expect(request.workflowId).toBe("workflow-1");
      expect(request.runId).toBe("run-1");
      expect(request.scope).toEqual(lowCostProposal.scope);
      expect(request.plan).toEqual(samplePlan);
      expect(request.estimatedCost).toBe(0.05);
      expect(request.riskLevel).toBe("low");
      expect(request.expiresAt).toBeDefined();
    });

    it("should auto-approve low-cost proposals", async () => {
      const request = await authority.requestApproval(lowCostProposal);

      const decision = authority.getDecision(request.requestId);
      expect(decision).toBeDefined();
      expect(decision?.approved).toBe(true);
      expect(decision?.decidedBy).toBe("policy");
    });

    it("should not auto-approve high-cost proposals", async () => {
      const highCostProposal: PlanProposal = {
        ...lowCostProposal,
        estimatedCost: 0.6,
        riskLevel: "high",
      };

      const request = await authority.requestApproval(highCostProposal);

      const decision = authority.getDecision(request.requestId);
      expect(decision).toBeUndefined();
    });

    it("should not auto-approve proposals with requiresApproval flag", async () => {
      const approvalRequired: PlanProposal = {
        ...lowCostProposal,
        requiresApproval: true,
      };

      const request = await authority.requestApproval(approvalRequired);

      const decision = authority.getDecision(request.requestId);
      expect(decision).toBeUndefined();
    });

    it("should not auto-approve proposals exceeding node threshold", async () => {
      const manyNodesPlan: PlanSpec = {
        ...samplePlan,
        nodes: Array.from({ length: 10 }, (_, i) => ({
          ...samplePlan.nodes[0],
          id: `node-${i}`,
        })),
      };

      const manyNodesProposal: PlanProposal = {
        ...lowCostProposal,
        plan: manyNodesPlan,
      };

      const request = await authority.requestApproval(manyNodesProposal);

      const decision = authority.getDecision(request.requestId);
      expect(decision).toBeUndefined();
    });
  });

  describe("decide", () => {
    it("should approve a request", async () => {
      const request = await authority.requestApproval({
        ...lowCostProposal,
        requiresApproval: true,
      });

      await authority.decide(request.requestId, {
        approved: true,
        decidedAt: new Date().toISOString(),
        decidedBy: "user",
        reason: "Looks good",
      });

      const decision = authority.getDecision(request.requestId);
      expect(decision?.approved).toBe(true);
      expect(decision?.decidedBy).toBe("user");
      expect(decision?.reason).toBe("Looks good");
    });

    it("should reject a request", async () => {
      const request = await authority.requestApproval({
        ...lowCostProposal,
        requiresApproval: true,
      });

      await authority.decide(request.requestId, {
        approved: false,
        decidedAt: new Date().toISOString(),
        decidedBy: "user",
        reason: "Too expensive",
      });

      const decision = authority.getDecision(request.requestId);
      expect(decision?.approved).toBe(false);
      expect(decision?.reason).toBe("Too expensive");
    });

    it("should create schedule entry on approval", async () => {
      const request = await authority.requestApproval({
        ...lowCostProposal,
        requiresApproval: true,
      });

      await authority.decide(request.requestId, {
        approved: true,
        decidedAt: new Date().toISOString(),
        decidedBy: "user",
      });

      const entries = authority.getScheduleEntriesByStatus("approved");
      expect(entries).toHaveLength(1);
      expect(entries[0].proposalId).toBe("proposal-1");
    });

    it("should not create schedule entry on rejection", async () => {
      const request = await authority.requestApproval({
        ...lowCostProposal,
        requiresApproval: true,
      });

      await authority.decide(request.requestId, {
        approved: false,
        decidedAt: new Date().toISOString(),
        decidedBy: "user",
      });

      const entries = authority.getAllScheduleEntries();
      expect(entries).toHaveLength(0);
    });

    it("should fail for non-existent request", async () => {
      await expect(
        authority.decide("non-existent", {
          approved: true,
          decidedAt: new Date().toISOString(),
          decidedBy: "user",
        }),
      ).rejects.toThrow("not found");
    });

    it("should fail for expired request", async () => {
      const request = await authority.requestApproval({
        ...lowCostProposal,
        requiresApproval: true,
      });

      // Manually expire the request
      const approvalRequest = authority.getApprovalRequest(request.requestId);
      if (approvalRequest) {
        approvalRequest.expiresAt = new Date(Date.now() - 1000).toISOString();
      }

      await expect(
        authority.decide(request.requestId, {
          approved: true,
          decidedAt: new Date().toISOString(),
          decidedBy: "user",
        }),
      ).rejects.toThrow("expired");
    });
  });

  describe("schedule", () => {
    it("should schedule an approved proposal", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const decision = authority.getDecision(request.requestId);
      expect(decision?.approved).toBe(true);

      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      expect(entry.scheduleId).toBeDefined();
      expect(entry.status).toBe("scheduled");
      expect(entry.scheduledFor).toBeDefined();
      expect(entry.priority).toBe(5);
    });

    it("should set custom priority", async () => {
      const request = await authority.requestApproval(lowCostProposal);

      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId, 10);

      expect(entry.priority).toBe(10);
    });

    it("should fail for non-approved request", async () => {
      const request = await authority.requestApproval({
        ...lowCostProposal,
        requiresApproval: true,
      });

      await expect(
        authority.schedule(lowCostProposal.proposalId, request.requestId),
      ).rejects.toThrow("not approved");
    });
  });

  describe("issueTicket", () => {
    it("should issue execution ticket for scheduled entry", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      const ticket = await authority.issueTicket(entry.scheduleId);

      expect(ticket.ticketId).toBeDefined();
      expect(ticket.scheduleId).toBe(entry.scheduleId);
      expect(ticket.workflowId).toBe("workflow-1");
      expect(ticket.runId).toBe("run-1");
      expect(ticket.plan).toEqual(samplePlan);
      expect(ticket.expiresAt).toBeDefined();
    });

    it("should update schedule entry status to executing", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      await authority.issueTicket(entry.scheduleId);

      const updated = authority.getScheduleEntry(entry.scheduleId);
      expect(updated?.status).toBe("executing");
      expect(updated?.startedAt).toBeDefined();
    });

    it("should fail for non-existent schedule", async () => {
      await expect(authority.issueTicket("non-existent")).rejects.toThrow("not found");
    });

    it("should fail for completed schedule", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      await authority.updateScheduleStatus(entry.scheduleId, "completed");

      await expect(authority.issueTicket(entry.scheduleId)).rejects.toThrow("Cannot issue ticket");
    });

    it("should enforce max concurrent executions", async () => {
      const policy = createDefaultAuthorityPolicy();
      policy.maxConcurrentExecutions = 1;
      const limitedAuthority = new BasicHostAuthority(policy);

      // Create and schedule first proposal
      const request1 = await limitedAuthority.requestApproval(lowCostProposal);
      const entry1 = await limitedAuthority.schedule(
        lowCostProposal.proposalId,
        request1.requestId,
      );
      await limitedAuthority.issueTicket(entry1.scheduleId);

      // Try to issue second ticket
      const proposal2: PlanProposal = {
        ...lowCostProposal,
        proposalId: "proposal-2",
        runId: "run-2",
      };
      const request2 = await limitedAuthority.requestApproval(proposal2);
      const entry2 = await limitedAuthority.schedule(proposal2.proposalId, request2.requestId);

      await expect(limitedAuthority.issueTicket(entry2.scheduleId)).rejects.toThrow(
        "Maximum concurrent executions",
      );
    });
  });

  describe("cancel", () => {
    it("should cancel scheduled execution", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      await authority.cancel(entry.scheduleId, "User requested");

      const updated = authority.getScheduleEntry(entry.scheduleId);
      expect(updated?.status).toBe("cancelled");
      expect(updated?.completedAt).toBeDefined();
    });

    it("should fail for non-existent schedule", async () => {
      await expect(authority.cancel("non-existent", "Test")).rejects.toThrow("not found");
    });

    it("should fail for completed schedule", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      await authority.updateScheduleStatus(entry.scheduleId, "completed");

      await expect(authority.cancel(entry.scheduleId, "Test")).rejects.toThrow("Cannot cancel");
    });
  });

  describe("getScheduleEntriesByStatus", () => {
    it("should filter by status", async () => {
      const request1 = await authority.requestApproval(lowCostProposal);
      const entry1 = await authority.schedule(lowCostProposal.proposalId, request1.requestId);

      const proposal2: PlanProposal = {
        ...lowCostProposal,
        proposalId: "proposal-2",
        runId: "run-2",
      };
      const request2 = await authority.requestApproval(proposal2);
      const entry2 = await authority.schedule(proposal2.proposalId, request2.requestId);

      await authority.issueTicket(entry1.scheduleId);

      const executing = authority.getScheduleEntriesByStatus("executing");
      const scheduled = authority.getScheduleEntriesByStatus("scheduled");

      expect(executing).toHaveLength(1);
      expect(executing[0].scheduleId).toBe(entry1.scheduleId);
      expect(scheduled).toHaveLength(1);
      expect(scheduled[0].scheduleId).toBe(entry2.scheduleId);
    });
  });

  describe("updateScheduleStatus", () => {
    it("should update status", async () => {
      const request = await authority.requestApproval(lowCostProposal);
      const entry = await authority.schedule(lowCostProposal.proposalId, request.requestId);

      await authority.updateScheduleStatus(entry.scheduleId, "completed");

      const updated = authority.getScheduleEntry(entry.scheduleId);
      expect(updated?.status).toBe("completed");
      expect(updated?.completedAt).toBeDefined();
    });

    it("should fail for non-existent schedule", async () => {
      await expect(authority.updateScheduleStatus("non-existent", "completed")).rejects.toThrow(
        "not found",
      );
    });
  });

  describe("createDefaultAuthorityPolicy", () => {
    it("should create valid policy", () => {
      const policy = createDefaultAuthorityPolicy();

      expect(policy.autoApproveThreshold.maxCost).toBe(0.1);
      expect(policy.autoApproveThreshold.maxDuration).toBe(60000);
      expect(policy.autoApproveThreshold.maxNodes).toBe(5);
      expect(policy.maxConcurrentExecutions).toBe(10);
      expect(policy.defaultPriority).toBe(5);
      expect(typeof policy.requireUserApproval).toBe("function");
    });
  });
});
