import type { ClaimedRun, RunLedger } from "./run-ledger.js";

export class RetryableRunError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RetryableRunError";
  }
}

class LeaseLostError extends RetryableRunError {
  constructor() {
    super("Worker lease lost");
    this.name = "LeaseLostError";
  }
}

class RunCancelledError extends Error {
  constructor() {
    super("Run cancelled");
    this.name = "RunCancelledError";
  }
}

export interface RunExecutor {
  execute(run: ClaimedRun, signal: AbortSignal): Promise<unknown>;
}

export interface RunWorkerOptions {
  workerId: string;
  leaseMs?: number;
  pollMs?: number;
  concurrency?: number;
}

export class DurableRunWorker {
  private stopped = true;
  private timer: NodeJS.Timeout | undefined;
  private readonly activeControllers = new Set<AbortController>();
  private readonly activeRuns = new Set<Promise<boolean>>();

  constructor(
    private readonly ledger: RunLedger,
    private readonly executor: RunExecutor,
    private readonly options: RunWorkerOptions,
  ) {}

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.loop();
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    for (const controller of this.activeControllers) {
      controller.abort(new RetryableRunError("Worker stopping"));
    }
    await Promise.allSettled(this.activeRuns);
  }

  async runOnce(): Promise<boolean> {
    const leaseMs = this.options.leaseMs ?? 30_000;
    const run = await this.ledger.claim(this.options.workerId, leaseMs);
    if (!run) return false;
    const token = run.fencing_token;
    const controller = new AbortController();
    this.activeControllers.add(controller);
    const heartbeat = setInterval(
      () => {
        void this.ledger
          .heartbeat(run.id, this.options.workerId, token, leaseMs)
          .then(async (alive) => {
            if (alive) return;
            const checkCancellation = (
              this.ledger as unknown as {
                isCancellationRequested?: (
                  runId: string,
                  workerId: string,
                  fencingToken: string,
                ) => Promise<boolean>;
              }
            ).isCancellationRequested;
            const cancelled =
              typeof checkCancellation === "function"
                ? await checkCancellation.call(this.ledger, run.id, this.options.workerId, token)
                : false;
            controller.abort(cancelled ? new RunCancelledError() : new LeaseLostError());
          })
          .catch(() => controller.abort(new LeaseLostError()));
      },
      Math.max(1_000, Math.floor(leaseMs / 3)),
    );
    try {
      const started = await this.ledger.transition(
        run.id,
        this.options.workerId,
        token,
        "leased",
        "running",
      );
      if (!started) return false;
      const output = await this.executor.execute(run, controller.signal);
      if (controller.signal.aborted) throw controller.signal.reason;
      await this.ledger.transition(run.id, this.options.workerId, token, "running", "completed", {
        output,
      });
      return true;
    } catch (error) {
      const reason = controller.signal.reason;
      const cancelled =
        error instanceof RunCancelledError ||
        reason instanceof RunCancelledError ||
        error === "task cancelled" ||
        reason === "task cancelled";
      const retryable =
        error instanceof RetryableRunError ||
        error instanceof LeaseLostError ||
        reason instanceof LeaseLostError;
      await this.ledger.transition(
        run.id,
        this.options.workerId,
        token,
        "running",
        cancelled ? "cancelled" : retryable ? "retryable" : "failed",
        { error: error instanceof Error ? error.message : String(error) },
      );
      return true;
    } finally {
      clearInterval(heartbeat);
      this.activeControllers.delete(controller);
    }
  }

  private async loop(): Promise<void> {
    while (!this.stopped) {
      const concurrency = Math.max(1, Math.floor(this.options.concurrency ?? 4));
      while (!this.stopped && this.activeRuns.size < concurrency) {
        const run = this.runOnce().catch(() => false);
        this.activeRuns.add(run);
        run.then(
          () => this.activeRuns.delete(run),
          () => this.activeRuns.delete(run),
        );
      }
      if (this.stopped) break;
      if (this.activeRuns.size) {
        await Promise.race(this.activeRuns);
      } else {
        await new Promise<void>((resolve) => {
          this.timer = setTimeout(resolve, this.options.pollMs ?? 250);
        });
      }
    }
  }
}
