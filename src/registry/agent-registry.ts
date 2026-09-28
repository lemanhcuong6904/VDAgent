/**
 * Agent Registry
 * Manages agent versions, activation states, and manifest validation
 */

import type { AgentManifest } from "../contracts/index.js";
import { ContractValidator } from "../testkit/contract-validator.js";

export type ActivationState = "pending" | "canary" | "enabled" | "disabled";

export interface AgentRegistration {
  id: string;
  version: string;
  manifest: AgentManifest;
  activationState: ActivationState;
  registeredAt: string;
  updatedAt: string;
  registeredBy: string;
  canaryPercentage?: number;
  allowlist?: string[];
}

export interface AgentVersionPin {
  agentId: string;
  version: string;
  policyRevision: string;
  pinnedAt: string;
}

export class AgentRegistry {
  private registrations = new Map<string, Map<string, AgentRegistration>>();
  private activations = new Map<string, string>(); // agentId -> active version
  private validator = new ContractValidator();

  /**
   * Register a new agent version with manifest validation
   */
  async register(
    registration: Omit<AgentRegistration, "registeredAt" | "updatedAt">,
  ): Promise<void> {
    // Validate manifest
    const validation = this.validator.validateManifest(registration.manifest);
    if (!validation.valid) {
      throw new Error(`Invalid manifest: ${validation.errors?.join(", ")}`);
    }

    // Check version format
    if (!this.isValidVersion(registration.version)) {
      throw new Error(`Invalid version format: ${registration.version}`);
    }

    // Store registration
    if (!this.registrations.has(registration.id)) {
      this.registrations.set(registration.id, new Map());
    }

    const versions = this.registrations.get(registration.id);
    if (!versions) throw new Error(`Failed to initialize versions for agent ${registration.id}`);
    const now = new Date().toISOString();

    versions.set(registration.version, {
      ...registration,
      registeredAt: now,
      updatedAt: now,
    });

    // Auto-enable if it's the first version and state is not explicitly set
    if (versions.size === 1 && registration.activationState === "enabled") {
      this.activations.set(registration.id, registration.version);
    }
  }

  /**
   * Update activation state for an agent version
   */
  async updateActivation(
    agentId: string,
    version: string,
    newState: ActivationState,
    options?: {
      canaryPercentage?: number;
      allowlist?: string[];
    },
  ): Promise<void> {
    const registration = this.getRegistration(agentId, version);
    if (!registration) {
      throw new Error(`Agent ${agentId}@${version} not found`);
    }

    // Update registration
    registration.activationState = newState;
    registration.updatedAt = new Date().toISOString();

    if (options?.canaryPercentage !== undefined) {
      registration.canaryPercentage = options.canaryPercentage;
    }
    if (options?.allowlist) {
      registration.allowlist = options.allowlist;
    }

    // Update active version pointer
    if (newState === "enabled") {
      this.activations.set(agentId, version);
    } else if (this.activations.get(agentId) === version) {
      // If disabling current active version, clear activation
      this.activations.delete(agentId);
    }
  }

  /**
   * Get active version for an agent
   */
  getActiveVersion(agentId: string): string | undefined {
    return this.activations.get(agentId);
  }

  /**
   * Get specific agent registration
   */
  getRegistration(agentId: string, version: string): AgentRegistration | undefined {
    return this.registrations.get(agentId)?.get(version);
  }

  /**
   * Get active agent registration
   */
  getActive(agentId: string): AgentRegistration | undefined {
    const version = this.getActiveVersion(agentId);
    if (!version) return undefined;
    return this.getRegistration(agentId, version);
  }

  /**
   * List all versions of an agent
   */
  listVersions(agentId: string): AgentRegistration[] {
    const versions = this.registrations.get(agentId);
    if (!versions) return [];
    return Array.from(versions.values()).sort((a, b) =>
      b.registeredAt.localeCompare(a.registeredAt),
    );
  }

  /**
   * List all agents
   */
  listAgents(): Array<{ id: string; activeVersion?: string; versions: number }> {
    return Array.from(this.registrations.entries()).map(([id, versions]) => ({
      id,
      activeVersion: this.activations.get(id),
      versions: versions.size,
    }));
  }

  /**
   * Check if user is in canary allowlist
   */
  isInCanaryAllowlist(agentId: string, version: string, userId: string): boolean {
    const registration = this.getRegistration(agentId, version);
    if (registration?.activationState !== "canary") {
      return false;
    }

    if (registration.allowlist?.includes(userId)) {
      return true;
    }

    // Check canary percentage (simple hash-based)
    if (registration.canaryPercentage) {
      const hash = this.simpleHash(userId);
      return hash % 100 < registration.canaryPercentage;
    }

    return false;
  }

  /**
   * Resolve which version to use for a specific user
   */
  resolveVersion(agentId: string, userId: string): string | undefined {
    // Check for canary versions
    const versions = this.listVersions(agentId);
    for (const reg of versions) {
      if (
        reg.activationState === "canary" &&
        this.isInCanaryAllowlist(agentId, reg.version, userId)
      ) {
        return reg.version;
      }
    }

    // Fall back to active version
    return this.getActiveVersion(agentId);
  }

  /**
   * Create version pin for a run
   */
  createVersionPin(agentId: string, version: string, policyRevision: string): AgentVersionPin {
    return {
      agentId,
      version,
      policyRevision,
      pinnedAt: new Date().toISOString(),
    };
  }

  /**
   * Validate version format (semver-like)
   */
  private isValidVersion(version: string): boolean {
    return /^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$/.test(version);
  }

  /**
   * Simple hash function for canary distribution
   */
  private simpleHash(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash = hash & hash; // Convert to 32-bit integer
    }
    return Math.abs(hash);
  }

  /**
   * Health check for an agent version
   */
  async healthCheck(
    agentId: string,
    version: string,
  ): Promise<{
    healthy: boolean;
    errors: string[];
  }> {
    const registration = this.getRegistration(agentId, version);
    if (!registration) {
      return { healthy: false, errors: ["Agent not found"] };
    }

    const errors: string[] = [];

    // Validate manifest
    const validation = this.validator.validateManifest(registration.manifest);
    if (!validation.valid) {
      errors.push(...(validation.errors || []));
    }

    // Check activation state
    if (registration.activationState === "disabled") {
      errors.push("Agent is disabled");
    }

    return {
      healthy: errors.length === 0,
      errors,
    };
  }

  /**
   * Rollback to previous version
   */
  async rollback(agentId: string): Promise<string | undefined> {
    const versions = this.listVersions(agentId);
    if (versions.length < 2) {
      return undefined;
    }

    // Get current active version
    const current = this.getActiveVersion(agentId);
    if (!current) {
      return undefined;
    }

    // Find the most recent version before current that can be activated
    // Skip the first one if it's the current version
    let foundCurrent = false;
    for (const reg of versions) {
      if (reg.version === current) {
        foundCurrent = true;
        continue;
      }

      // After finding current, take the next one (which is older due to DESC sort)
      if (
        foundCurrent &&
        (reg.activationState === "enabled" || reg.activationState === "pending")
      ) {
        await this.updateActivation(agentId, reg.version, "enabled");
        return reg.version;
      }
    }

    return undefined;
  }
}
