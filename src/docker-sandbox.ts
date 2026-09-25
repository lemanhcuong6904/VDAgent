import { createHash } from "node:crypto";
import { request } from "node:http";
import type { SandboxCommand, SandboxProvider } from "./sandbox.js";
import type { ToolScope } from "./tool-pool.js";

const MAX_OUTPUT_BYTES = 256_000;
const SANDBOX_IMAGE = process.env.SANDBOX_IMAGE ?? "node:24-slim";
const DOCKER_SOCKET = process.env.DOCKER_SOCKET ?? "/var/run/docker.sock";

type DockerResponse = Record<string, unknown>;
export class DockerSandboxProvider implements SandboxProvider {
  execute(input: SandboxCommand, scope: ToolScope) {
    return executeDocker(input.argv, input.cwd ?? "/workspace", input.timeoutMs ?? 30_000, scope);
  }
}

function dockerRequest(path: string, body?: unknown, method = "POST"): Promise<DockerResponse> {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const req = request(
      {
        socketPath: DOCKER_SOCKET,
        path: `/v1.45${path}`,
        method,
        headers: payload
          ? { "content-type": "application/json", "content-length": Buffer.byteLength(payload) }
          : {},
      },
      (res) => {
        const chunks: Buffer[] = [];
        let bytes = 0;
        res.on("data", (chunk: Buffer) => {
          bytes += chunk.byteLength;
          if (bytes > MAX_OUTPUT_BYTES) {
            req.destroy(new Error("Sandbox output exceeded the byte limit"));
            return;
          }
          chunks.push(chunk);
        });
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          const value = text ? (JSON.parse(text) as DockerResponse) : {};
          if ((res.statusCode ?? 500) >= 400) {
            reject(
              new Error(
                typeof value.message === "string" ? value.message : "Docker request failed",
              ),
            );
          } else resolve(value);
        });
      },
    );
    req.setTimeout(30_000, () => req.destroy(new Error("Docker request timed out")));
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

function dockerStream(path: string, body: unknown, signal: AbortSignal): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const chunks: Buffer[] = [];
    let bytes = 0;
    const req = request(
      {
        socketPath: DOCKER_SOCKET,
        path: `/v1.45${path}`,
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": Buffer.byteLength(payload),
        },
      },
      (res) => {
        res.on("data", (chunk: Buffer) => {
          bytes += chunk.byteLength;
          if (bytes > MAX_OUTPUT_BYTES) {
            req.destroy(new Error("Sandbox output exceeded the byte limit"));
            return;
          }
          chunks.push(chunk);
        });
        res.on("end", () => {
          if ((res.statusCode ?? 500) >= 400) {
            reject(new Error(Buffer.concat(chunks).toString("utf8")));
          } else resolve(Buffer.concat(chunks));
        });
      },
    );
    const abort = () =>
      req.destroy(
        signal.reason instanceof Error ? signal.reason : new Error("Sandbox command cancelled"),
      );
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    req.on("close", () => signal.removeEventListener("abort", abort));
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

function containerName(scope: ToolScope): string {
  if (!scope.agentId) throw new Error("Sandbox requires an agent identity");
  const key = createHash("sha256")
    .update([scope.spaceId, scope.userId, scope.agentId].join("\0"))
    .digest("hex")
    .slice(0, 32);
  return `team6-agent-${key}`;
}

async function ensureContainer(scope: ToolScope): Promise<string> {
  const name = containerName(scope);
  try {
    const existing = await dockerRequest(`/containers/${name}/json`, undefined, "GET");
    if (existing.State && typeof existing.State === "object" && "Running" in existing.State) {
      const state = existing.State as { Running: boolean };
      if (!state.Running) await dockerRequest(`/containers/${name}/start`, {});
    }
    return name;
  } catch (error) {
    if (!(error instanceof Error) || !error.message.includes("No such container")) throw error;
  }

  const volume = `${name}-workspace`;
  await dockerRequest("/volumes/create", {
    Name: volume,
    Labels: { "team6.agent": scope.agentId },
  });
  try {
    await dockerRequest(`/containers/create?name=${name}`, {
      Image: SANDBOX_IMAGE,
      Cmd: ["sh", "-c", "chown 1000:1000 /workspace && exec sleep infinity"],
      Labels: { "team6.agent": scope.agentId },
      WorkingDir: "/workspace",
      HostConfig: {
        NetworkMode: "none",
        ReadonlyRootfs: true,
        Memory: 536_870_912,
        NanoCpus: 1_000_000_000,
        PidsLimit: 128,
        CapDrop: ["ALL"],
        CapAdd: ["CHOWN"],
        SecurityOpt: ["no-new-privileges:true"],
        Tmpfs: { "/tmp": "rw,noexec,nosuid,size=64m" },
        Binds: [`${volume}:/workspace`],
      },
    });
  } catch (error) {
    if (!(error instanceof Error) || !error.message.includes("Conflict")) throw error;
  }
  await dockerRequest(`/containers/${name}/start`, {});
  return name;
}

async function executeDocker(argv: string[], cwd: string, timeoutMs: number, scope: ToolScope) {
  const name = await ensureContainer(scope);
  scope.signal.throwIfAborted();
  const created = await dockerRequest(`/containers/${name}/exec`, {
    Cmd: argv,
    WorkingDir: cwd,
    User: "1000:1000",
    AttachStdout: true,
    AttachStderr: true,
    Tty: false,
  });
  const execId = created.Id;
  if (typeof execId !== "string") throw new Error("Docker did not return an exec ID");
  const timeoutController = new AbortController();
  const timer = setTimeout(
    () => timeoutController.abort(new Error("Sandbox command timed out")),
    timeoutMs,
  );
  const signal = AbortSignal.any([scope.signal, timeoutController.signal]);
  let output: Buffer;
  try {
    output = await dockerStream(`/exec/${execId}/start`, { Detach: false, Tty: false }, signal);
  } finally {
    clearTimeout(timer);
  }
  const inspected = await dockerRequest(`/exec/${execId}/json`, undefined, "GET");
  return { exitCode: inspected.ExitCode ?? null, output: decodeExecOutput(output) };
}

function decodeExecOutput(stream: Buffer): { stdout: string; stderr: string } {
  const output = { stdout: "", stderr: "" };
  for (let offset = 0; offset + 8 <= stream.length; ) {
    const streamType = stream[offset];
    const length = stream.readUInt32BE(offset + 4);
    offset += 8;
    if (offset + length > stream.length) throw new Error("Docker returned an invalid exec stream");
    const text = stream.toString("utf8", offset, offset + length);
    if (streamType === 1) output.stdout += text;
    else if (streamType === 2) output.stderr += text;
    offset += length;
  }
  return output;
}
