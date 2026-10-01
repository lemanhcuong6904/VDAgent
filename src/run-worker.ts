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
  private pollWake: (() => void) | undefined;
  private loopTask: Promise<void> | undefined;
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
    this.loopTask = this.loop().finally(() => {
      this.loopTask = undefined;
    });
  }

  async stop(): Promise<void> {
    await this.drain(0);
  }

  /** Runs currently executing on this worker. */
  get activeCount(): number {
    return this.activeRuns.size;
  }

  /**
   * Stop claiming, give in-flight runs `graceMs` to finish, then abort the rest as
   * retryable so another worker re-claims them once their lease lapses. Resolves with
   * how many runs finished on their own and how many were handed back.
   */
  async drain(graceMs: number): Promise<{ finished: number; handedBack: number }> {
    this.stopped = true;
    this.wakePoller();
    const inFlight = this.activeRuns.size;
    if (graceMs > 0 && inFlight > 0) {
      let timer: NodeJS.Timeout | undefined;
      await Promise.race([
        Promise.allSettled(this.activeRuns),
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, graceMs);
        }),
      ]);
      clearTimeout(timer);
    }
    const handedBack = this.activeControllers.size;
    for (const controller of this.activeControllers) {
      controller.abort(new RetryableRunError("Worker stopping"));
    }
    await Promise.allSettled(this.activeRuns);
    await this.loopTask;
    return { finished: inFlight - handedBack, handedBack };
  }

  async runOnce(stopIfWorkerStops = false): Promise<boolean> {
    const leaseMs = this.options.leaseMs ?? 30_000;
    const run = await this.ledger.claim(this.options.workerId, leaseMs);
    if (!run) return false;
    const token = run.fencing_token;
    if (stopIfWorkerStops && this.stopped) {
      await this.ledger.transition(run.id, this.options.workerId, token, "leased", "retryable", {
        error: "Worker stopping before execution",
      });
      return true;
    }
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
      Math.max(50, Math.floor(leaseMs / 3)),
    );
    const deadlineTimer = run.deadline_at
      ? setTimeout(
          () => controller.abort(new Error("Run deadline exceeded")),
          Math.max(0, run.deadline_at.getTime() - Date.now()),
        )
      : undefined;
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
      if (deadlineTimer) clearTimeout(deadlineTimer);
      this.activeControllers.delete(controller);
    }
  }

  private async loop(): Promise<void> {
    while (!this.stopped) {
      const concurrency = Math.max(1, Math.floor(this.options.concurrency ?? 4));
      while (!this.stopped && this.activeRuns.size < concurrency) {
        const run = this.runOnce(true).catch(() => false);
        this.activeRuns.add(run);
        run.then(
          () => this.activeRuns.delete(run),
          () => this.activeRuns.delete(run),
        );
      }
      if (this.stopped) break;
      if (this.activeRuns.size) {
        const claimed = await Promise.race(this.activeRuns);
        // Empty claims must not immediately refill the slot. Otherwise the worker
        // continuously opens database transactions and never reaches pollMs sleep.
        if (!claimed && !this.stopped) await this.waitForPoll();
      } else {
        await this.waitForPoll();
      }
    }
  }

  private waitForPoll(): Promise<void> {
    return new Promise((resolve) => {
      this.pollWake = resolve;
      this.timer = setTimeout(() => {
        this.timer = undefined;
        this.pollWake = undefined;
        resolve();
      }, this.options.pollMs ?? 250);
    });
  }

  private wakePoller(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = undefined;
    const wake = this.pollWake;
    this.pollWake = undefined;
    wake?.();
  }
}
