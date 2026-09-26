import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

export const AGENT_RUNNER_PROTOCOL = "agent-runner.v1" as const;

export interface AgentRunnerRequest {
  requestId: string;
  agentId: string;
  agentVersion: string;
  input: unknown;
  scope: {
    userId: string;
    spaceId: string;
    taskId?: string;
    runId?: string;
    parentRunId?: string;
    traceId?: string;
  };
  tools: readonly string[];
  deadlineAt?: string;
}

export interface AgentRunnerToolCall {
  requestId: string;
  callId: string;
  name: string;
  input: unknown;
}

export interface AgentRunner {
  run(request: AgentRunnerRequest, signal: AbortSignal): Promise<unknown>;
}

export interface JsonLineAgentRunnerOptions {
  command: string;
  args?: readonly string[];
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  onToolCall?: (call: AgentRunnerToolCall) => Promise<unknown>;
  onStderr?: (chunk: string) => void;
}

type RunnerMessage =
  | {
      protocol: typeof AGENT_RUNNER_PROTOCOL;
      type: "tool_call";
      request_id: string;
      call_id: string;
      name: string;
      input: unknown;
    }
  | {
      protocol: typeof AGENT_RUNNER_PROTOCOL;
      type: "result";
      request_id: string;
      ok: boolean;
      output?: unknown;
      error?: string;
    }
  | {
      protocol: typeof AGENT_RUNNER_PROTOCOL;
      type: "event";
      request_id: string;
      event: string;
      data?: unknown;
    };

/** Spawns one isolated agent process per invocation and speaks JSONL over stdin/stdout. */
export class JsonLineAgentRunner implements AgentRunner {
  constructor(private readonly options: JsonLineAgentRunnerOptions) {}

  async run(request: AgentRunnerRequest, signal: AbortSignal): Promise<unknown> {
    signal.throwIfAborted();
    const child = spawn(this.options.command, [...(this.options.args ?? [])], {
      cwd: this.options.cwd,
      env: safeRunnerEnvironment(this.options.env),
      stdio: ["pipe", "pipe", "pipe"],
    });
    return new Promise<unknown>((resolve, reject) => {
      const lines = createInterface({ input: child.stdout });
      let settled = false;
      let killTimer: NodeJS.Timeout | undefined;

      const finish = (error?: Error, output?: unknown) => {
        if (settled) return;
        settled = true;
        if (killTimer) clearTimeout(killTimer);
        signal.removeEventListener("abort", abort);
        lines.close();
        if (!child.killed) child.kill();
        if (error) reject(error);
        else resolve(output);
      };

      const write = (message: Record<string, unknown>) => {
        if (child.stdin.destroyed || !child.stdin.writable) {
          throw new Error("Agent runner stdin is closed");
        }
        child.stdin.write(`${JSON.stringify(message)}\n`);
      };

      const abort = () => {
        try {
          write({ protocol: AGENT_RUNNER_PROTOCOL, type: "cancel", request_id: request.requestId });
        } catch {
          // The process may have exited between the signal and the cancel message.
        }
        killTimer = setTimeout(() => child.kill("SIGTERM"), 1_000);
      };

      const handleToolCall = async (message: Extract<RunnerMessage, { type: "tool_call" }>) => {
        try {
          if (!this.options.onToolCall) throw new Error("Agent has no tool bridge");
          const output = await this.options.onToolCall({
            requestId: message.request_id,
            callId: message.call_id,
            name: message.name,
            input: message.input,
          });
          write({
            protocol: AGENT_RUNNER_PROTOCOL,
            type: "tool_result",
            request_id: message.request_id,
            call_id: message.call_id,
            ok: true,
            output,
          });
        } catch (error) {
          write({
            protocol: AGENT_RUNNER_PROTOCOL,
            type: "tool_result",
            request_id: message.request_id,
            call_id: message.call_id,
            ok: false,
            error: error instanceof Error ? error.message : String(error),
          });
        }
      };

      lines.on("line", (line) => {
        if (settled || !line.trim()) return;
        let parsed: unknown;
        try {
          parsed = JSON.parse(line);
        } catch {
          finish(new Error("Agent runner emitted invalid JSON"));
          return;
        }
        if (!isRunnerMessage(parsed) || parsed.request_id !== request.requestId) {
          finish(new Error("Agent runner emitted an invalid protocol message"));
          return;
        }
        if (parsed.type === "tool_call") {
          void handleToolCall(parsed);
        } else if (parsed.type === "event") {
          // Events are intentionally observable by the host only through stderr/telemetry for now.
        } else if (parsed.ok) {
          finish(undefined, parsed.output);
        } else {
          finish(new Error(parsed.error ?? "Agent runner failed"));
        }
      });
      child.stderr.on("data", (chunk: Buffer) => this.options.onStderr?.(chunk.toString("utf8")));
      child.once("error", (error) => finish(error));
      child.once("close", (code, signalName) => {
        if (!settled) {
          finish(
            new Error(
              `Agent runner exited before returning a result (${signalName ?? `code ${code ?? "unknown"}`})`,
            ),
          );
        }
      });
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) abort();
      try {
        write({
          protocol: AGENT_RUNNER_PROTOCOL,
          type: "run",
          request_id: request.requestId,
          agent_id: request.agentId,
          agent_version: request.agentVersion,
          input: request.input,
          scope: request.scope,
          tools: request.tools,
          deadline_at: request.deadlineAt,
        });
      } catch (error) {
        finish(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }
}

/** Keep process basics needed to launch an agent, but never inherit platform credentials. */
function safeRunnerEnvironment(overrides: NodeJS.ProcessEnv | undefined): NodeJS.ProcessEnv {
  const allowed =
    /^(PATH|PYTHONPATH|PYTHONHOME|VIRTUAL_ENV|HOME|LANG|LC_[A-Z_]+|TZ|TMPDIR|TMP|TEMP|SYSTEMROOT|WINDIR)$/i;
  const blocked = /(api[_-]?key|token|secret|password|credential|database|dsn|docker)/i;
  const result: NodeJS.ProcessEnv = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && allowed.test(key) && !blocked.test(key)) result[key] = value;
  }
  for (const [key, value] of Object.entries(overrides ?? {})) {
    if (value !== undefined && allowed.test(key) && !blocked.test(key)) result[key] = value;
  }
  return result;
}

function isRunnerMessage(value: unknown): value is RunnerMessage {
  return (
    typeof value === "object" &&
    value !== null &&
    "protocol" in value &&
    value.protocol === AGENT_RUNNER_PROTOCOL &&
    "type" in value &&
    typeof value.type === "string" &&
    "request_id" in value &&
    typeof value.request_id === "string"
  );
}
