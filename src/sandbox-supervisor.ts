import type { SandboxCommand, SandboxProvider } from "./sandbox.js";
import type { ToolScope } from "./tool-pool.js";

export interface SandboxSupervisorOptions {
  maxConcurrentPerAgent?: number;
  maxCommandTimeoutMs?: number;
}

/** Policy boundary shared by Docker and future gVisor/Kata adapters. */
export class SandboxSupervisor implements SandboxProvider {
  private readonly active = new Map<string, number>();
  private readonly maxConcurrent: number;
  private readonly maxTimeout: number;

  constructor(
    private readonly provider: SandboxProvider,
    options: SandboxSupervisorOptions = {},
  ) {
    this.maxConcurrent = Math.max(1, options.maxConcurrentPerAgent ?? 2);
    this.maxTimeout = Math.min(300_000, Math.max(1_000, options.maxCommandTimeoutMs ?? 300_000));
  }

  async execute(input: SandboxCommand, scope: ToolScope): Promise<unknown> {
    if (!scope.agentId) throw new Error("Sandbox requires an agent identity");
    if (input.argv.length === 0 || input.argv.length > 64)
      throw new Error("Invalid sandbox command");
    const active = this.active.get(scope.agentId) ?? 0;
    if (active >= this.maxConcurrent) throw new Error("Sandbox concurrency quota exceeded");
    const timeoutMs = Math.min(input.timeoutMs ?? 30_000, this.maxTimeout);
    this.active.set(scope.agentId, active + 1);
    try {
      return await this.provider.execute({ ...input, timeoutMs }, scope);
    } finally {
      const next = (this.active.get(scope.agentId) ?? 1) - 1;
      if (next > 0) this.active.set(scope.agentId, next);
      else this.active.delete(scope.agentId);
    }
  }

  async cleanup(scope: ToolScope): Promise<void> {
    const cleanup = (
      this.provider as SandboxProvider & { cleanup?: (scope: ToolScope) => Promise<void> }
    ).cleanup;
    await cleanup?.(scope);
  }
}
