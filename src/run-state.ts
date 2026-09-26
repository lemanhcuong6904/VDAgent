export type RunStatus =
  | "queued"
  | "leased"
  | "running"
  | "waiting"
  | "retryable"
  | "completed"
  | "failed"
  | "cancelled";

const transitions: Record<RunStatus, readonly RunStatus[]> = {
  queued: ["leased", "cancelled"],
  leased: ["running", "retryable", "failed", "cancelled"],
  running: ["waiting", "completed", "retryable", "failed", "cancelled"],
  waiting: ["running", "completed", "retryable", "failed", "cancelled"],
  retryable: ["queued", "cancelled"],
  completed: [],
  failed: [],
  cancelled: [],
};

export function assertRunTransition(from: RunStatus, to: RunStatus): void {
  if (!transitions[from].includes(to)) {
    throw new Error(`Invalid run transition '${from}' -> '${to}'`);
  }
}

export function isTerminalRunStatus(status: RunStatus): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}
