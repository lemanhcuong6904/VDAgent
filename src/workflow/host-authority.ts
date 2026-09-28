/**
 * Host Authority
 * Authority for plan approval, scheduling, and execution control
 * Planner proposes, host decides
 */

import type { AgentScope } from "../contracts/index.js";
import type { PlanProposal } from "./planner.js";
import type { PlanSpec } from "./workflow-module.js";

/**
 * Approval decision
 */
export interface ApprovalDecision {
  approved: boolean;
  decidedAt: string;
  decidedBy: "user" | "system" | "policy";
  reason?: string;
  conditions?: string[];
  expiresAt?: string;
}

/**
 * Approval request
 */
export interface ApprovalRequest {
  requestId: string;
  proposalId: string;
  workflowId: string;
  runId: string;
  scope: AgentScope;
  plan: PlanSpec;
  estimatedCost: number;
  estimatedDuration: number;
  riskLevel: "low" | "medium" | "high";
  rationale: string;
  requestedAt: string;
  expiresAt?: string;
}

/**
 * Schedule entry
 */
export interface ScheduleEntry {
  scheduleId: string;
  workflowId: string;
  runId: string;
  proposalId: string;
  approvalRequestId?: string;
  status:
    | "pending_approval"
    | "approved"
    | "rejected"
    | "scheduled"
    | "executing"
    | "completed"
    | "failed"
    | "cancelled";
  plan: PlanSpec;
  scope: AgentScope;
  scheduledFor?: string;
  startedAt?: string;
  completedAt?: string;
  priority: number;
  createdAt: string;
}

/**
 * Execution ticket
 */
export interface ExecutionTicket {
  ticketId: string;
  scheduleId: string;
  workflowId: string;
  runId: string;
  plan: PlanSpec;
  scope: AgentScope;
  issuedAt: string;
  expiresAt: string;
  usedAt?: string;
}

/**
 * Authority policy
 */
export interface AuthorityPolicy {
  autoApproveThreshold: {
    maxCost: number;
    maxDuration: number;
    maxNodes: number;
  };
  requireUserApproval: (proposal: PlanProposal) => boolean;
  maxConcurrentExecutions: number;
  defaultPriority: number;
}

/**
 * Host authority interface
 */
export interface IHostAuthority {
  /**
   * Request approval for a plan proposal
   */
  requestApproval(proposal: PlanProposal): Promise<ApprovalRequest>;

  /**
   * Approve or reject an approval request
   */
  decide(requestId: string, decision: ApprovalDecision): Promise<void>;

  /**
   * Schedule an approved plan for execution
   */
  schedule(
    proposalId: string,
    approvalRequestId: string,
    priority?: number,
  ): Promise<ScheduleEntry>;

  /**
   * Issue execution ticket for scheduled plan
   */
  issueTicket(scheduleId: string): Promise<ExecutionTicket>;

  /**
   * Cancel scheduled execution
   */
  cancel(scheduleId: string, reason: string): Promise<void>;

  /**
   * Get approval request status
   */
  getApprovalRequest(requestId: string): ApprovalRequest | undefined;

  /**
   * Get schedule entry
   */
  getScheduleEntry(scheduleId: string): ScheduleEntry | undefined;
}

/**
 * Basic host authority implementation
 */
export class BasicHostAuthority implements IHostAuthority {
  private approvalRequests: Map<string, ApprovalRequest> = new Map();
  private decisions: Map<string, ApprovalDecision> = new Map();
  private scheduleEntries: Map<string, ScheduleEntry> = new Map();
  private tickets: Map<string, ExecutionTicket> = new Map();
  private proposals: Map<string, PlanProposal> = new Map();

  constructor(private policy: AuthorityPolicy) {}

  async requestApproval(proposal: PlanProposal): Promise<ApprovalRequest> {
    this.proposals.set(proposal.proposalId, proposal);

    const request: ApprovalRequest = {
      requestId: this.generateId(),
      proposalId: proposal.proposalId,
      workflowId: proposal.workflowId,
      runId: proposal.runId,
      scope: proposal.scope,
      plan: proposal.plan,
      estimatedCost: proposal.estimatedCost,
      estimatedDuration: proposal.estimatedDuration,
      riskLevel: proposal.riskLevel,
      rationale: proposal.rationale,
      requestedAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 3600000).toISOString(), // 1 hour expiry
    };

    this.approvalRequests.set(request.requestId, request);

    // Auto-approve if within policy thresholds
    if (this.shouldAutoApprove(proposal)) {
      const autoDecision: ApprovalDecision = {
        approved: true,
        decidedAt: new Date().toISOString(),
        decidedBy: "policy",
        reason: "Auto-approved within policy thresholds",
      };
      await this.decide(request.requestId, autoDecision);
    }

    return request;
  }

  async decide(requestId: string, decision: ApprovalDecision): Promise<void> {
    const request = this.approvalRequests.get(requestId);
    if (!request) {
      throw new Error(`Approval request ${requestId} not found`);
    }

    // Check expiry
    if (request.expiresAt && new Date(request.expiresAt) < new Date()) {
      throw new Error(`Approval request ${requestId} has expired`);
    }

    this.decisions.set(requestId, decision);

    // If approved, create schedule entry
    if (decision.approved) {
      const proposal = this.proposals.get(request.proposalId);
      if (!proposal) {
        throw new Error(`Proposal ${request.proposalId} not found`);
      }

      const entry: ScheduleEntry = {
        scheduleId: this.generateId(),
        workflowId: request.workflowId,
        runId: request.runId,
        proposalId: request.proposalId,
        approvalRequestId: requestId,
        status: "approved",
        plan: request.plan,
        scope: request.scope,
        priority: this.policy.defaultPriority,
        createdAt: new Date().toISOString(),
      };

      this.scheduleEntries.set(entry.scheduleId, entry);
    }
  }

  async schedule(
    proposalId: string,
    approvalRequestId: string,
    priority?: number,
  ): Promise<ScheduleEntry> {
    const decision = this.decisions.get(approvalRequestId);
    if (!decision?.approved) {
      throw new Error(`Approval request ${approvalRequestId} not approved`);
    }

    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      throw new Error(`Proposal ${proposalId} not found`);
    }

    const request = this.approvalRequests.get(approvalRequestId);
    if (!request) {
      throw new Error(`Approval request ${approvalRequestId} not found`);
    }

    // Find or create schedule entry
    let entry = Array.from(this.scheduleEntries.values()).find(
      (e) => e.proposalId === proposalId && e.approvalRequestId === approvalRequestId,
    );

    if (!entry) {
      entry = {
        scheduleId: this.generateId(),
        workflowId: proposal.workflowId,
        runId: proposal.runId,
        proposalId,
        approvalRequestId,
        status: "scheduled",
        plan: proposal.plan,
        scope: request.scope,
        scheduledFor: new Date().toISOString(),
        priority: priority ?? this.policy.defaultPriority,
        createdAt: new Date().toISOString(),
      };
      this.scheduleEntries.set(entry.scheduleId, entry);
    } else {
      entry.status = "scheduled";
      entry.scheduledFor = new Date().toISOString();
      if (priority !== undefined) {
        entry.priority = priority;
      }
    }

    return entry;
  }

  async issueTicket(scheduleId: string): Promise<ExecutionTicket> {
    const entry = this.scheduleEntries.get(scheduleId);
    if (!entry) {
      throw new Error(`Schedule entry ${scheduleId} not found`);
    }

    if (entry.status !== "scheduled" && entry.status !== "approved") {
      throw new Error(
        `Cannot issue ticket for schedule entry ${scheduleId} in status ${entry.status}`,
      );
    }

    // Check concurrent execution limit
    const executingCount = Array.from(this.scheduleEntries.values()).filter(
      (e) => e.status === "executing",
    ).length;

    if (executingCount >= this.policy.maxConcurrentExecutions) {
      throw new Error(
        `Maximum concurrent executions (${this.policy.maxConcurrentExecutions}) reached`,
      );
    }

    const ticket: ExecutionTicket = {
      ticketId: this.generateId(),
      scheduleId,
      workflowId: entry.workflowId,
      runId: entry.runId,
      plan: entry.plan,
      scope: entry.scope,
      issuedAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 3600000).toISOString(), // 1 hour
    };

    this.tickets.set(ticket.ticketId, ticket);

    // Update schedule entry
    entry.status = "executing";
    entry.startedAt = ticket.issuedAt;

    return ticket;
  }

  async cancel(scheduleId: string, _reason: string): Promise<void> {
    const entry = this.scheduleEntries.get(scheduleId);
    if (!entry) {
      throw new Error(`Schedule entry ${scheduleId} not found`);
    }

    if (entry.status === "completed" || entry.status === "failed") {
      throw new Error(
        `Cannot cancel schedule entry ${scheduleId} in terminal status ${entry.status}`,
      );
    }

    entry.status = "cancelled";
    entry.completedAt = new Date().toISOString();
  }

  getApprovalRequest(requestId: string): ApprovalRequest | undefined {
    return this.approvalRequests.get(requestId);
  }

  getScheduleEntry(scheduleId: string): ScheduleEntry | undefined {
    return this.scheduleEntries.get(scheduleId);
  }

  /**
   * Get decision for approval request
   */
  getDecision(requestId: string): ApprovalDecision | undefined {
    return this.decisions.get(requestId);
  }

  /**
   * Get all schedule entries
   */
  getAllScheduleEntries(): ScheduleEntry[] {
    return Array.from(this.scheduleEntries.values());
  }

  /**
   * Get schedule entries by status
   */
  getScheduleEntriesByStatus(status: ScheduleEntry["status"]): ScheduleEntry[] {
    return Array.from(this.scheduleEntries.values()).filter((e) => e.status === status);
  }

  /**
   * Update schedule entry status
   */
  async updateScheduleStatus(scheduleId: string, status: ScheduleEntry["status"]): Promise<void> {
    const entry = this.scheduleEntries.get(scheduleId);
    if (!entry) {
      throw new Error(`Schedule entry ${scheduleId} not found`);
    }

    entry.status = status;

    if (status === "completed" || status === "failed" || status === "cancelled") {
      entry.completedAt = new Date().toISOString();
    }
  }

  private shouldAutoApprove(proposal: PlanProposal): boolean {
    const { autoApproveThreshold, requireUserApproval } = this.policy;

    // Check if user approval explicitly required
    if (requireUserApproval(proposal)) {
      return false;
    }

    // Check if proposal requires approval flag
    if (proposal.requiresApproval) {
      return false;
    }

    // Check thresholds
    if (proposal.estimatedCost > autoApproveThreshold.maxCost) {
      return false;
    }

    if (proposal.estimatedDuration > autoApproveThreshold.maxDuration) {
      return false;
    }

    if (proposal.plan.nodes.length > autoApproveThreshold.maxNodes) {
      return false;
    }

    return true;
  }

  private generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
  }
}

/**
 * Create default authority policy
 */
export function createDefaultAuthorityPolicy(): AuthorityPolicy {
  return {
    autoApproveThreshold: {
      maxCost: 0.1, // $0.10
      maxDuration: 60000, // 1 minute
      maxNodes: 5,
    },
    requireUserApproval: (proposal: PlanProposal) => {
      return proposal.riskLevel === "high" || proposal.estimatedCost > 0.5;
    },
    maxConcurrentExecutions: 10,
    defaultPriority: 5,
  };
}
