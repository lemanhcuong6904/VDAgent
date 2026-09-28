/**
 * Agent Runner v2
 * Process-based agent execution with v2 protocol support
 */

import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import type {
  AgentMessage,
  AgentScope,
  CancelMessage,
  HostMessage,
  InvokeMessage,
  PortCallMessage,
  PortResultMessage,
  ProtocolMessage,
  StructuredError,
} from "./agent-protocol.js";
import {
  AGENT_PROTOCOL,
  isProtocolMessage,
  parseMessage,
  serializeMessage,
} from "./agent-protocol.js";

export interface ProcessAgentRequest {
  requestId: string;
  agentId: string;
  agentVersion?: string;
  input: unknown;
  scope: AgentScope;
  tools?: readonly string[];
  deadlineAt?: string;
  checkpointId?: string;
  idempotencyKey?: string;
}

export interface PortCall {
  requestId: string;
  callId: string;
  port: string;
  operation: string;
  input?: unknown;
  sequence?: number;
  idempotencyKey?: string;
}

export interface ProcessAgentRunnerOptions {
  command: string;
  args?: readonly string[];
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  onPortCall?: (call: PortCall) => Promise<unknown>;
  onEvent?: (event: string, data?: unknown) => void;
  onCheckpoint?: (checkpointId: string, manifest?: unknown) => void;
  onStderr?: (chunk: string) => void;
  authorizationCheck?: (port: string, operation: string) => Promise<boolean>;
}

export interface AgentRunner {
  run(request: ProcessAgentRequest, signal: AbortSignal): Promise<unknown>;
}

export class AgentDeadlineExceededError extends Error {
  readonly code = "AGENT_DEADLINE_EXCEEDED";

  constructor() {
    super("Agent execution exceeded its deadline");
    this.name = "AgentDeadlineExceededError";
  }
}

/** V2 agent runner with full protocol support including authorization, checkpointing, and events */
export class ProcessAgentRunner implements AgentRunner {
  constructor(private readonly options: ProcessAgentRunnerOptions) {}

  async run(request: ProcessAgentRequest, signal: AbortSignal): Promise<unknown> {
    signal.throwIfAborted();

    const deadline = request.deadlineAt === undefined ? undefined : Date.parse(request.deadlineAt);
    if (deadline !== undefined && !Number.isFinite(deadline)) {
      throw new Error("Agent runner received an invalid deadline");
    }
    if (deadline !== undefined && deadline <= Date.now()) {
      throw new AgentDeadlineExceededError();
    }

    const child = spawn(this.options.command, [...(this.options.args ?? [])], {
      cwd: this.options.cwd,
      env: safeRunnerEnvironment(this.options.env),
      stdio: ["pipe", "pipe", "pipe"],
      // A detached child has its own process group on POSIX. Cancellation can
      // then terminate grandchildren that would survive child.kill().
      detached: process.platform !== "win32",
    });

    return new Promise<unknown>((resolve, reject) => {
      const lines = createInterface({ input: child.stdout });
      let settled = false;
      let deadlineTimer: NodeJS.Timeout | undefined;
      const terminationTimers: NodeJS.Timeout[] = [];
      let terminationStarted = false;
      let sequenceCounter = 0;

      const signalProcessTree = (signalName: NodeJS.Signals) => {
        if (process.platform !== "win32" && child.pid !== undefined) {
          try {
            process.kill(-child.pid, signalName);
          } catch {
            // The group may have exited between the check and the signal.
          }
          return;
        }
        try {
          child.kill(signalName);
        } catch {
          // The process may have exited between the check and the signal.
        }
      };

      const terminateProcessTree = (gracefulCancel: boolean) => {
        if (terminationStarted) return;
        terminationStarted = true;
        if (gracefulCancel) {
          terminationTimers.push(setTimeout(() => signalProcessTree("SIGTERM"), 250));
          terminationTimers.push(setTimeout(() => signalProcessTree("SIGKILL"), 1_250));
        } else {
          signalProcessTree("SIGTERM");
          // Result frames do not imply the agent has closed its descendants.
          terminationTimers.push(setTimeout(() => signalProcessTree("SIGKILL"), 1_000));
        }
        for (const timer of terminationTimers) timer.unref();
      };

      const finish = (error?: Error, output?: unknown, gracefulCancel = false) => {
        if (settled) return;
        settled = true;
        if (deadlineTimer) clearTimeout(deadlineTimer);
        signal.removeEventListener("abort", abort);
        lines.close();
        terminateProcessTree(gracefulCancel);
        if (error) reject(error);
        else resolve(output);
      };

      const write = (message: HostMessage) => {
        if (child.stdin.destroyed || !child.stdin.writable) {
          throw new Error("Agent runner stdin is closed");
        }
        child.stdin.write(`${serializeMessage(message)}\n`);
      };

      const sendCancel = (reason: string) => {
        try {
          const cancelMessage: CancelMessage = {
            protocol: AGENT_PROTOCOL,
            type: "cancel",
            request_id: request.requestId,
            reason,
          };
          write(cancelMessage);
        } catch {
          // Process may have exited or closed its input.
        }
      };

      const abort = () => {
        const reason = signal.reason;
        sendCancel(reason instanceof Error ? reason.message : "Aborted by caller");
        finish(
          reason instanceof Error ? reason : new Error("Agent execution was cancelled"),
          undefined,
          true,
        );
      };

      const armDeadline = () => {
        if (deadline === undefined || settled) return;
        const remaining = deadline - Date.now();
        if (remaining <= 0) {
          sendCancel("Agent execution exceeded its deadline");
          finish(new AgentDeadlineExceededError(), undefined, true);
          return;
        }
        deadlineTimer = setTimeout(armDeadline, Math.min(remaining, 2_147_483_647));
      };

      const handlePortCall = async (message: PortCallMessage) => {
        try {
          // M9.3: Authorization check
          if (this.options.authorizationCheck) {
            const authorized = await this.options.authorizationCheck(
              message.port,
              message.operation,
            );
            if (settled) return;
            if (!authorized) {
              const errorResult: PortResultMessage = {
                protocol: AGENT_PROTOCOL,
                type: "port_result",
                request_id: message.request_id,
                call_id: message.call_id,
                ok: false,
                error: {
                  code: "unauthorized",
                  message: `Port call to ${message.port}.${message.operation} not authorized`,
                  retriable: false,
                },
                sequence: ++sequenceCounter,
              };
              write(errorResult);
              return;
            }
          }

          // M9.3: Sequence validation
          if (message.sequence !== undefined && message.sequence < sequenceCounter) {
            const errorResult: PortResultMessage = {
              protocol: AGENT_PROTOCOL,
              type: "port_result",
              request_id: message.request_id,
              call_id: message.call_id,
              ok: false,
              error: {
                code: "sequence_error",
                message: `Sequence number ${message.sequence} is less than expected ${sequenceCounter}`,
                retriable: false,
              },
              sequence: ++sequenceCounter,
            };
            write(errorResult);
            return;
          }

          if (!this.options.onPortCall) {
            throw new Error("Agent has no port bridge");
          }

          const output = await this.options.onPortCall({
            requestId: message.request_id,
            callId: message.call_id,
            port: message.port,
            operation: message.operation,
            input: message.input,
            sequence: message.sequence,
            idempotencyKey: message.idempotency_key,
          });

          if (settled) return;

          const successResult: PortResultMessage = {
            protocol: AGENT_PROTOCOL,
            type: "port_result",
            request_id: message.request_id,
            call_id: message.call_id,
            ok: true,
            output,
            sequence: ++sequenceCounter,
          };
          write(successResult);
        } catch (error) {
          if (settled) return;
          const errorResult: PortResultMessage = {
            protocol: AGENT_PROTOCOL,
            type: "port_result",
            request_id: message.request_id,
            call_id: message.call_id,
            ok: false,
            error: structuredError(error),
            sequence: ++sequenceCounter,
          };
          try {
            write(errorResult);
          } catch {
            // Cancellation may close stdin while an in-flight host bridge settles.
          }
        }
      };

      lines.on("line", (line) => {
        if (settled || !line.trim()) return;

        let message: ProtocolMessage;
        try {
          message = parseMessage(line);
        } catch {
          finish(new Error("Agent runner emitted invalid protocol v2 message"));
          return;
        }

        if (!isProtocolMessage(message) || !isAgentMessage(message)) {
          finish(new Error("Agent runner emitted an invalid message type"));
          return;
        }

        if ("request_id" in message && message.request_id !== request.requestId) {
          finish(new Error("Agent runner emitted message with mismatched request_id"));
          return;
        }

        switch (message.type) {
          case "port_call":
            void handlePortCall(message);
            break;

          case "event":
            this.options.onEvent?.(message.event, message.data);
            break;

          case "checkpoint":
            this.options.onCheckpoint?.(message.checkpoint_id, message.manifest);
            break;

          case "wait":
            // The host does not have a resume/wait channel. Treating this as a
            // no-op would let an agent continue under false assumptions.
            finish(new Error("Agent runner wait messages are not supported by this host"));
            break;

          case "result":
            if (message.ok) {
              finish(undefined, message.output);
            } else {
              finish(new Error(message.error?.message ?? "Agent runner failed"));
            }
            break;
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
      if (signal.aborted) {
        abort();
        return;
      }
      armDeadline();
      if (settled) return;

      try {
        const invokeMessage: InvokeMessage = {
          protocol: AGENT_PROTOCOL,
          type: "invoke",
          request_id: request.requestId,
          agent_id: request.agentId,
          agent_version: request.agentVersion,
          input: request.input,
          scope: request.scope,
          tools: request.tools,
          deadline_at: request.deadlineAt,
          checkpoint_id: request.checkpointId,
          idempotency_key: request.idempotencyKey,
        };
        write(invokeMessage);
      } catch (error) {
        finish(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }
}

function isAgentMessage(message: ProtocolMessage): message is AgentMessage {
  return (
    message.type === "port_call" ||
    message.type === "event" ||
    message.type === "checkpoint" ||
    message.type === "wait" ||
    message.type === "result"
  );
}

function structuredError(error: unknown): StructuredError {
  if (error instanceof Error) {
    return {
      code: "agent_error",
      message: error.message,
      retriable: false,
    };
  }
  return {
    code: "unknown_error",
    message: String(error),
    retriable: false,
  };
}

/** Keep process basics needed to launch an agent, but never inherit platform credentials */
function safeRunnerEnvironment(overrides: NodeJS.ProcessEnv | undefined): NodeJS.ProcessEnv {
  const allowed =
    /^(PATH|PYTHONPATH|PYTHONHOME|VIRTUAL_ENV|HOME|LANG|LC_[A-Z_]+|TZ|TMPDIR|TMP|TEMP|SYSTEMROOT|WINDIR)$/i;
  const blocked = /(api[_-]?key|token|secret|password|credential|database|dsn|docker)/i;
  const result: NodeJS.ProcessEnv = {};

  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && allowed.test(key) && !blocked.test(key)) {
      result[key] = value;
    }
  }

  for (const [key, value] of Object.entries(overrides ?? {})) {
    if (value !== undefined && allowed.test(key) && !blocked.test(key)) {
      result[key] = value;
    }
  }

  return result;
}
