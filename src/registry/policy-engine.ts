/**
 * Policy Engine
 * Enforces capability/grant intersection and policy revision tracking
 */

import type { AgentManifest, AgentScope, ToolGrant } from "../contracts/index.js";

type Capability = AgentManifest["capabilities"][number];

export interface PolicyRevision {
  id: string;
  version: string;
  effectiveAt: string;
  rules: PolicyRule[];
  metadata?: {
    author?: string;
    description?: string;
    approvedBy?: string;
  };
}

export interface PolicyRule {
  id: string;
  type: "capability" | "tool" | "resource" | "budget";
  effect: "allow" | "deny";
  conditions?: PolicyCondition[];
  priority: number;
}

export interface PolicyCondition {
  field: string;
  operator: "eq" | "ne" | "in" | "not_in" | "gt" | "lt" | "matches";
  value: unknown;
}

export interface Grant {
  capability?: Capability;
  toolId?: string;
  resourcePattern?: string;
  scope: GrantScope;
  constraints?: GrantConstraints;
}

export interface GrantScope {
  tenantId: string;
  workspaceId?: string;
  audience?: string[];
}

export interface GrantConstraints {
  maxUsage?: number;
  expiresAt?: string;
  allowedAgents?: string[];
  deniedAgents?: string[];
}

export interface PolicyViolation {
  type: "missing_capability" | "missing_tool_grant" | "budget_exceeded" | "unauthorized_scope";
  message: string;
  capability?: Capability;
  toolId?: string;
  actualValue?: unknown;
  limitValue?: unknown;
}

export class PolicyEngine {
  private revisions = new Map<string, PolicyRevision>();
  private grants = new Map<string, Grant[]>(); // tenantId -> grants
  private activeRevision: string | undefined;

  /**
   * Register a policy revision
   */
  registerRevision(revision: PolicyRevision): void {
    this.revisions.set(revision.id, revision);
  }

  /**
   * Activate a policy revision
   */
  activateRevision(revisionId: string): void {
    if (!this.revisions.has(revisionId)) {
      throw new Error(`Policy revision not found: ${revisionId}`);
    }
    this.activeRevision = revisionId;
  }

  /**
   * Get active policy revision
   */
  getActiveRevision(): PolicyRevision | undefined {
    if (!this.activeRevision) return undefined;
    return this.revisions.get(this.activeRevision);
  }

  /**
   * Grant capabilities to a tenant
   */
  grant(tenantId: string, grant: Grant): void {
    if (!this.grants.has(tenantId)) {
      this.grants.set(tenantId, []);
    }
    const grants = this.grants.get(tenantId);
    if (!grants) throw new Error(`Failed to initialize grants for tenant ${tenantId}`);
    grants.push(grant);
  }

  /**
   * Revoke all grants for a tenant
   */
  revokeAll(tenantId: string): void {
    this.grants.delete(tenantId);
  }

  /**
   * Check if manifest capabilities are authorized for scope
   */
  authorize(
    manifest: AgentManifest,
    scope: AgentScope,
    policyRevisionId?: string,
  ): { authorized: boolean; violations: PolicyViolation[] } {
    const violations: PolicyViolation[] = [];

    // Use specified revision or active revision
    const revisionId = policyRevisionId || this.activeRevision;
    const revision = revisionId ? this.revisions.get(revisionId) : undefined;

    // Get grants for tenant
    const tenantGrants = this.grants.get(scope.tenantId) || [];

    // Check each capability
    for (const capability of manifest.capabilities) {
      if (!this.hasCapabilityGrant(capability, tenantGrants, scope)) {
        violations.push({
          type: "missing_capability",
          message: `Missing grant for capability: ${capability}`,
          capability,
        });
      }
    }

    // Check tool grants (required, possibly empty, in the canonical manifest)
    for (const toolGrant of manifest.toolGrants) {
      if (!this.hasToolGrant(toolGrant, tenantGrants, scope)) {
        violations.push({
          type: "missing_tool_grant",
          message: `Missing grant for tool: ${toolGrant.toolId}`,
          toolId: toolGrant.toolId,
        });
      }
    }

    // Apply policy rules if revision exists
    if (revision) {
      const ruleViolations = this.applyPolicyRules(revision.rules, manifest, scope);
      violations.push(...ruleViolations);
    }

    return {
      authorized: violations.length === 0,
      violations,
    };
  }

  /**
   * Check if capability grant exists
   */
  private hasCapabilityGrant(capability: Capability, grants: Grant[], scope: AgentScope): boolean {
    return grants.some((grant) => {
      // Check capability match
      if (grant.capability !== capability) return false;

      // Check scope match
      if (grant.scope.tenantId !== scope.tenantId) return false;
      if (grant.scope.workspaceId && grant.scope.workspaceId !== scope.workspaceId) {
        return false;
      }
      // A grant audience list (if any) must include the scope's single audience
      if (grant.scope.audience && !grant.scope.audience.includes(scope.audience)) return false;

      // Check constraints
      if (grant.constraints) {
        if (grant.constraints.expiresAt) {
          const expiresAt = new Date(grant.constraints.expiresAt);
          if (expiresAt < new Date()) return false;
        }
      }

      return true;
    });
  }

  /**
   * Check if tool grant exists
   */
  private hasToolGrant(toolGrant: ToolGrant, grants: Grant[], scope: AgentScope): boolean {
    return grants.some((grant) => {
      // Check tool match
      if (grant.toolId !== toolGrant.toolId) return false;

      // Check scope match (same as capability)
      if (grant.scope.tenantId !== scope.tenantId) return false;
      if (grant.scope.workspaceId && grant.scope.workspaceId !== scope.workspaceId) {
        return false;
      }

      // Check constraints
      if (grant.constraints) {
        if (grant.constraints.expiresAt) {
          const expiresAt = new Date(grant.constraints.expiresAt);
          if (expiresAt < new Date()) return false;
        }
      }

      return true;
    });
  }

  /**
   * Apply policy rules
   */
  private applyPolicyRules(
    rules: PolicyRule[],
    manifest: AgentManifest,
    scope: AgentScope,
  ): PolicyViolation[] {
    const violations: PolicyViolation[] = [];

    // Sort rules by priority (higher first)
    const sortedRules = [...rules].sort((a, b) => b.priority - a.priority);

    for (const rule of sortedRules) {
      // Check if rule conditions match
      if (rule.conditions && !this.evaluateConditions(rule.conditions, scope, manifest)) {
        continue;
      }

      // Apply rule based on type
      if (rule.type === "capability" && rule.effect === "deny") {
        // Check if any manifest capability is denied
        for (const capability of manifest.capabilities) {
          violations.push({
            type: "missing_capability",
            message: `Capability denied by policy: ${capability}`,
            capability,
          });
        }
      }

      if (rule.type === "budget") {
        // Budget rules would check manifest.limits against policy
        const maxCost = manifest.limits.maxCostUsd;
        // In a real implementation, you'd extract budget limit from rule conditions
        // For now, use a default threshold of 0.5 USD
        const budgetLimit = 0.5;
        if (maxCost > budgetLimit) {
          violations.push({
            type: "budget_exceeded",
            message: `Max cost ${maxCost} exceeds policy limit ${budgetLimit}`,
            actualValue: maxCost,
            limitValue: budgetLimit,
          });
        }
      }
    }

    return violations;
  }

  /**
   * Evaluate policy conditions
   */
  private evaluateConditions(
    conditions: PolicyCondition[],
    scope: AgentScope,
    manifest: AgentManifest,
  ): boolean {
    return conditions.every((condition) => {
      const value = this.getFieldValue(condition.field, scope, manifest);

      switch (condition.operator) {
        case "eq":
          return value === condition.value;
        case "ne":
          return value !== condition.value;
        case "in":
          return Array.isArray(condition.value) && condition.value.includes(value);
        case "not_in":
          return Array.isArray(condition.value) && !condition.value.includes(value);
        case "gt":
          return typeof value === "number" && value > (condition.value as number);
        case "lt":
          return typeof value === "number" && value < (condition.value as number);
        case "matches":
          return (
            typeof value === "string" &&
            typeof condition.value === "string" &&
            new RegExp(condition.value).test(value)
          );
        default:
          return false;
      }
    });
  }

  /**
   * Get field value from scope or manifest
   */
  private getFieldValue(field: string, scope: AgentScope, manifest: AgentManifest): unknown {
    // Check scope fields
    if (field in scope) {
      return Reflect.get(scope, field);
    }

    // Check manifest fields
    if (field in manifest) {
      return Reflect.get(manifest, field);
    }

    // Handle nested fields
    const parts = field.split(".");
    let value: unknown = { ...scope, ...manifest };
    for (const part of parts) {
      if (value && typeof value === "object" && part in value) {
        value = Reflect.get(value, part);
      } else {
        return undefined;
      }
    }
    return value;
  }

  /**
   * Pin policy revision for a run
   */
  createPolicyPin(revisionId?: string): {
    revisionId: string;
    pinnedAt: string;
  } {
    const effectiveRevisionId = revisionId || this.activeRevision;
    if (!effectiveRevisionId) {
      throw new Error("No policy revision to pin");
    }

    if (!this.revisions.has(effectiveRevisionId)) {
      throw new Error(`Policy revision not found: ${effectiveRevisionId}`);
    }

    return {
      revisionId: effectiveRevisionId,
      pinnedAt: new Date().toISOString(),
    };
  }

  /**
   * Validate pinned policy still exists
   */
  validatePin(revisionId: string): boolean {
    return this.revisions.has(revisionId);
  }

  /**
   * Check audience leakage
   */
  checkAudienceLeakage(
    sourceScope: AgentScope,
    targetScope: AgentScope,
  ): { safe: boolean; violation?: PolicyViolation } {
    // Canonical scope carries exactly one audience; any change between scopes is leakage
    if (sourceScope.audience !== targetScope.audience) {
      return {
        safe: false,
        violation: {
          type: "unauthorized_scope",
          message: "Audience leakage detected: source audience not subset of target",
        },
      };
    }

    return { safe: true };
  }

  /**
   * Check tenant isolation
   */
  checkTenantIsolation(
    sourceScope: AgentScope,
    targetScope: AgentScope,
  ): { safe: boolean; violation?: PolicyViolation } {
    if (sourceScope.tenantId !== targetScope.tenantId) {
      return {
        safe: false,
        violation: {
          type: "unauthorized_scope",
          message: `Tenant isolation violation: ${sourceScope.tenantId} -> ${targetScope.tenantId}`,
        },
      };
    }

    return { safe: true };
  }
}
