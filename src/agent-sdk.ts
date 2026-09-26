/** Stable ports exposed to team-owned agents; implementations remain in the platform host. */
export interface AgentScope {
  userId: string;
  spaceId: string;
  taskId?: string;
  runId?: string;
  parentRunId?: string;
  signal: AbortSignal;
  traceId?: string;
}

export interface ToolClient {
  call<TOutput = unknown>(name: string, input: unknown): Promise<TOutput>;
}

export interface WarehouseClient {
  listSources(): Promise<unknown>;
  describe(input: unknown): Promise<unknown>;
  query<TOutput = unknown>(input: unknown): Promise<TOutput>;
}

export interface ArtifactClient {
  read<TOutput = unknown>(id: string): Promise<TOutput>;
  write<TOutput = unknown>(kind: string, input: unknown): Promise<TOutput>;
}

export interface AgentClient {
  catalog(input?: { capability?: string }): Promise<unknown>;
  delegate<TOutput = unknown>(input: {
    agent?: string;
    capability?: string;
    message: string;
  }): Promise<TOutput>;
  send<TOutput = unknown>(input: {
    agent?: string;
    capability?: string;
    message: string;
    idempotencyKey?: string;
  }): Promise<TOutput>;
  wait<TOutput = unknown>(runId: string): Promise<TOutput>;
  result<TOutput = unknown>(runId: string): Promise<TOutput>;
}

export interface AgentSdk {
  scope: AgentScope;
  tools: ToolClient;
  warehouse: WarehouseClient;
  artifacts: ArtifactClient;
  agents: AgentClient;
}
