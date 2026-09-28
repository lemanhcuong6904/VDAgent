// DTOs mirroring the REST / SSE contract (spec §10).

export type Role = "user" | "assistant" | "tool";

export interface ToolCallDTO {
  id: string;
  name: string;
  arguments_json: string;
}

export interface MessageDTO {
  id: number;
  seq: number;
  task_id: string;
  invocation_id: string;
  role: Role;
  sender: string | null;
  content: string;
  tool_calls: ToolCallDTO[] | null;
  tool_call_id: string | null;
  compacted: boolean;
  created_at: string;
}

export type TaskStatus = "running" | "completed" | "failed" | "cancelled";

export interface TaskDTO {
  id: string;
  root_agent: string;
  status: TaskStatus;
  created_at: string;
  finished_at: string | null;
}

export type InvocationStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "rejected";

export interface InvocationDTO {
  id: string;
  task_id: string;
  agent: string;
  caller: string;
  parent_id: string | null;
  tool_call_id: string | null;
  depth: number;
  inbound_text: string;
  status: InvocationStatus;
  result_text: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface UserDTO {
  id: string;
  name: string;
}

export interface AgentDTO {
  name: string;
  description: string;
  healthy: boolean;
  busy: boolean;
  queue_len: number;
}

export interface PendingDTO {
  invocation_id: string;
  caller: string;
  inbound_text: string;
  created_at: string;
}

/** `GET /api/agents/{agent}/messages` — newest page, ascending `seq`. */
export interface MessagesPageDTO {
  summary: string | null;
  messages: MessageDTO[];
  pending: PendingDTO[];
}

export interface PostMessageResponseDTO {
  task_id: string;
  invocation_id: string;
}

export interface TaskDetailDTO {
  task: TaskDTO;
  invocations: InvocationDTO[];
}

export interface CancelTaskResponseDTO {
  task: TaskDTO;
}

export interface ColumnDTO {
  name: string;
  type: string;
}

export interface DatasetDTO {
  id: string;
  name: string | null;
  columns: ColumnDTO[];
  row_count: number;
  truncated: boolean;
  source_sql: string;
  rows: unknown[][];
}

export interface ChartDTO {
  id: string;
  title: string;
  dataset_id: string;
  spec: Record<string, unknown>;
}

export interface ReportSummaryDTO {
  id: string;
  title: string;
  created_at: string;
}

export interface ReportDTO {
  id: string;
  title: string;
  markdown: string;
  created_at: string;
}

export interface ErrorEnvelopeDTO {
  error: { code: string; message: string };
}

// ---- SSE (`GET /api/events?user_id=`) ----

export interface MessageAppendedData {
  agent: string;
  message: MessageDTO;
}

export interface InvocationUpdatedData {
  invocation: InvocationDTO;
}

export interface TaskUpdatedData {
  task: TaskDTO;
}

export interface AgentStatusData {
  agent: string;
  healthy: boolean;
  busy: boolean;
  queue_len: number;
}

export type ServerEvent =
  | { event: "message.appended"; data: MessageAppendedData }
  | { event: "invocation.updated"; data: InvocationUpdatedData }
  | { event: "task.updated"; data: TaskUpdatedData }
  | { event: "agent.status"; data: AgentStatusData };

export type ServerEventName = ServerEvent["event"];

export const SERVER_EVENT_NAMES: readonly ServerEventName[] = [
  "message.appended",
  "invocation.updated",
  "task.updated",
  "agent.status",
];

// ---- /api/v1 run view (M12.3). Mirrors `RunView` in src/run-view.ts. ----

export type RunStatusV1 =
  | "queued"
  | "leased"
  | "running"
  | "waiting"
  | "retryable"
  | "completed"
  | "failed"
  | "cancelled";

export interface UsageTotalsDTO {
  records: number;
  inputTokens: number;
  outputTokens: number;
  latencyMs: number;
  estimatedCost: number;
}

export interface RunGraphNodeDTO {
  id: string;
  kind: "planner" | "agent" | "tool" | "approval";
  agentId: string | null;
  capability: string | null;
  status: "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled";
  attempt: number;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
}

export interface RunViewDTO {
  run: {
    id: string;
    workflowId: string;
    workflowVersion: string;
    status: RunStatusV1;
    createdAt: string;
    updatedAt: string;
    finishedAt: string | null;
    durationMs: number | null;
    terminal: boolean;
    cancelRequested: boolean;
  };
  graph: { nodes: RunGraphNodeDTO[]; edges: { from: string; to: string }[]; roots: string[] };
  approvals: {
    stepId: string;
    state: "pending" | "approved" | "rejected" | "cancelled";
    requestedAt: string | null;
    decidedAt: string | null;
    waitedMs: number | null;
  }[];
  artifacts: {
    id: string;
    kind: string;
    version: string;
    status: "pending" | "ready" | "failed";
    sha256: string | null;
    bytes: number | null;
    verified: boolean;
    contentUrl: string | null;
  }[];
  evidence: {
    counts: { verified: number; unverified: number; unavailable: number };
    items: {
      id: string;
      kind: "source" | "tool_call" | "model_call" | "artifact_ref" | "checkpoint";
      verification: "verified" | "unverified" | "unavailable";
      ref: string;
      createdAt: string;
    }[];
    truncated: boolean;
  };
  cost: {
    totals: UsageTotalsDTO;
    byModel: Record<string, UsageTotalsDTO>;
    byAgent: Record<string, UsageTotalsDTO>;
  };
  errors: { source: "run" | "step" | "event"; ref: string; message: string; at: string }[];
  receipt: {
    status: "success" | "failure" | "timeout" | "cancelled";
    sealedAt: string;
    evidenceCount: number;
    verifiedEvidenceCount: number;
    durationMs: number | null;
  } | null;
  permissions: { canCancel: boolean; canDecideApproval: boolean };
  truncated: boolean;
}

/** `GET /api/v1/legacy/tasks/{id}/run` — bridge from a legacy task to its durable run. */
export interface TaskRunLinkDTO {
  task_id: string;
  run_id: string;
  events: string;
  stream: string;
}
