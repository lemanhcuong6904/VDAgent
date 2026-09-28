/**
 * Process lifecycle - M13.1
 * Liveness, readiness and ordered shutdown for the API and worker processes.
 *
 *   live  : the process is up and its event loop answers. Never checks dependencies,
 *           so a database outage does not make an orchestrator restart every replica.
 *   ready : safe to route traffic here. False while starting, while draining, when
 *           the database is unreachable, or when the schema does not match this build.
 */

import type { MigrationStatus } from "./database.js";

export type LifecyclePhase = "starting" | "ready" | "draining" | "stopped";

export interface ReadinessReport {
  ready: boolean;
  phase: LifecyclePhase;
  checks: {
    database: "ok" | "unreachable";
    schema: "ok" | "pending" | "ahead";
  };
  pending?: string[];
  unknown?: string[];
}

export interface ShutdownStep {
  name: string;
  run(): Promise<unknown>;
}

export interface ShutdownResult {
  ok: boolean;
  steps: Array<{ name: string; ok: boolean; ms: number }>;
  timedOut: boolean;
}

export class Lifecycle {
  private current: LifecyclePhase = "starting";

  constructor(
    private readonly probes: {
      ping(): Promise<unknown>;
      migrations(): Promise<MigrationStatus>;
    },
  ) {}

  get phase(): LifecyclePhase {
    return this.current;
  }

  markReady(): void {
    if (this.current === "starting") this.current = "ready";
  }

  async readiness(): Promise<ReadinessReport> {
    const phase = this.current;
    let database: ReadinessReport["checks"]["database"] = "ok";
    let schema: ReadinessReport["checks"]["schema"] = "ok";
    let status: MigrationStatus | undefined;
    try {
      await this.probes.ping();
      status = await this.probes.migrations();
      // Unknown (newer) migrations mean this image is older than the schema. Serving
      // could write rows the newer code cannot read, so the replica stays out of rotation.
      if (status.unknown.length > 0) schema = "ahead";
      else if (status.pending.length > 0) schema = "pending";
    } catch {
      database = "unreachable";
    }
    return {
      ready: phase === "ready" && database === "ok" && schema === "ok",
      phase,
      checks: { database, schema },
      ...(status && status.pending.length > 0 && { pending: status.pending }),
      ...(status && status.unknown.length > 0 && { unknown: status.unknown }),
    };
  }

  /**
   * Leave rotation, wait `drainDelayMs` so load balancers observe the failing
   * readiness, then run each step in order. A failing step does not skip the rest:
   * the database pool must still close after a worker drain throws. The whole
   * sequence is bounded by `timeoutMs`.
   */
  async shutdown(
    steps: readonly ShutdownStep[],
    options: { drainDelayMs: number; timeoutMs: number },
  ): Promise<ShutdownResult> {
    if (this.current === "draining" || this.current === "stopped") {
      return { ok: false, steps: [], timedOut: false };
    }
    this.current = "draining";
    const results: ShutdownResult["steps"] = [];
    let timer: NodeJS.Timeout | undefined;
    const deadline = new Promise<"timeout">((resolve) => {
      timer = setTimeout(() => resolve("timeout"), options.timeoutMs);
    });
    const sequence = (async () => {
      if (options.drainDelayMs > 0)
        await new Promise((resolve) => setTimeout(resolve, options.drainDelayMs));
      for (const step of steps) {
        const started = Date.now();
        try {
          await step.run();
          results.push({ name: step.name, ok: true, ms: Date.now() - started });
        } catch {
          results.push({ name: step.name, ok: false, ms: Date.now() - started });
        }
      }
      return "done" as const;
    })();
    const outcome = await Promise.race([sequence, deadline]);
    clearTimeout(timer);
    this.current = "stopped";
    return {
      ok: outcome === "done" && results.every((step) => step.ok),
      steps: [...results],
      timedOut: outcome === "timeout",
    };
  }
}
