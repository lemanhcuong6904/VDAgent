import type { AgentMessage } from "@earendil-works/pi-agent-core";

export interface PiSessionScope {
  userId: string;
  spaceId: string;
  agentId: string;
  sessionId: string;
}

export interface PiSessionSnapshot {
  messages: AgentMessage[];
  revision: number;
}

export interface PiSessionLease {
  load(): Promise<PiSessionSnapshot>;
  save(messages: AgentMessage[], expectedRevision: number): Promise<number>;
  release(): Promise<void>;
}

export interface PiSessionStore {
  open(scope: PiSessionScope): Promise<PiSessionLease>;
}
