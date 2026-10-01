// SandboxPort: host-owned commands, policy check, output limit, idempotent replay, Docker isolation.
import { Type } from "typebox";
import { describe, expect, it } from "vitest";
import type { AgentContext } from "../../src/agent-contract.js";
import type { AgentManifest } from "../../src/contracts/index.js";
import { DockerSandboxProvider } from "../../src/docker-sandbox.js";
import { createHostSandboxPort } from "../../src/ports/host-sandbox.js";
import { createSandboxTool, type SandboxProvider } from "../../src/sandbox.js";
import { SandboxSupervisor } from "../../src/sandbox-supervisor.js";
import { McpToolPool } from "../../src/tool-pool.js";

const manifest = (grants = ["sandbox.execute"]): AgentManifest =>
  ({
    apiVersion: "agent.v1",
    id: "test.sandbox",
    version: "1.0.0",
    requiredPorts: ["sandbox"],
    toolGrants: grants.map((toolId) => ({ toolId, version: "1", effect: "write" })),
  }) as unknown as AgentManifest;

function setup(provider: SandboxProvider, grants?: string[]) {
  const pool = new McpToolPool();
  pool.register(createSandboxTool(provider));
  const stored: unknown[] = [];
  pool.register({
    name: "artifacts.store",
    description: "store",
    schema: Type.Any(),
    mutates: true,
    agents: ["*"],
    authorize: () => true,
    execute: async (input: unknown) => {
      stored.push(input);
      return { id: "art-1", sha256: "x", bytes: 1 };
    },
  });
  const context = {
    runId: "run-1",
    sessionId: "s",
    userId: "u",
    spaceId: "space",
    tools: pool.forAgent("test.sandbox"),
    pool,
  } as unknown as AgentContext;
  return { port: createHostSandboxPort(manifest(grants), context, "run-1"), stored };
}
const live = () => ({ signal: new AbortController().signal, deadline: Date.now() + 60_000 });
const call = (patch: Record<string, unknown> = {}) => ({
  commandId: "node.eval",
  arguments: { source: "console.log(1)" },
  inputArtifacts: [],
  credentialRefs: [],
  maxOutputBytes: 4096,
  idempotencyKey: "k1",
  ...patch,
});

describe("host sandbox port", () => {
  const argvs: string[][] = [];
  const fake: SandboxProvider = {
    execute: async (input) => {
      argvs.push(input.argv);
      return { exitCode: 0, output: { stdout: "1\n", stderr: "" } };
    },
  };

  it("builds argv on the host and replays by idempotency key", async () => {
    const { port } = setup(fake);
    const first = await port.execute(call(), live());
    expect(first).toMatchObject({ status: "ok", output: { exitCode: 0, artifacts: [] } });
    expect(await port.execute(call(), live())).toBe(first);
    expect(argvs).toEqual([["node", "-e", "console.log(1)"]]);
  });

  it("stores output as an artifact when artifacts.store is granted", async () => {
    const { port, stored } = setup(fake, ["sandbox.execute", "artifacts.store"]);
    const result = await port.execute(call(), live());
    expect(result).toMatchObject({ status: "ok", output: { artifacts: [{ id: "art-1" }] } });
    expect(stored).toHaveLength(1);
  });

  it("fails closed on unknown commands, bad args, credentials, artifacts and missing grant", async () => {
    const { port } = setup(fake);
    const code = async (patch: Record<string, unknown>) => {
      const result = await port.execute(
        call({ idempotencyKey: `k${Math.random()}`.replace(".", ""), ...patch }),
        live(),
      );
      return "error" in result ? result.error.code : result.status;
    };
    expect(await code({ commandId: "sh" })).toBe("unknown_command");
    expect(await code({ commandId: "constructor" })).toBe("unknown_command");
    expect(await code({ arguments: { source: 1 } })).toBe("invalid_command_arguments");
    expect(await code({ arguments: { source: "x", argv: ["sh"] } })).toBe(
      "invalid_command_arguments",
    );
    expect(await code({ credentialRefs: ["db"] })).toBe("sandbox_policy_credential");
    expect(await code({ inputArtifacts: ["a1"] })).toBe("sandbox_input_artifacts_unsupported");
    const ungranted = setup(fake, []).port;
    expect(await ungranted.execute(call(), live())).toMatchObject({
      status: "denied",
      error: { code: "sandbox_not_granted" },
    });
  });

  it("reports unknown when output exceeds the limit or the run fails", async () => {
    const { port } = setup(fake);
    expect(await port.execute(call({ maxOutputBytes: 5 }), live())).toMatchObject({
      status: "unknown",
      error: { code: "output_limit" },
    });
    const broken = setup({ execute: async () => Promise.reject(new Error("boom")) }).port;
    expect(await broken.execute(call(), live())).toMatchObject({
      status: "unknown",
      error: { code: "sandbox_outcome_unknown" },
    });
  });

  it("does not pretend to support pause/resume", async () => {
    const { port } = setup(fake);
    expect(await port.pause({ executionId: "e", idempotencyKey: "p" }, live())).toMatchObject({
      status: "denied",
      error: { code: "sandbox_pause_unsupported" },
    });
  });
});

// Needs a real Docker daemon: TEAM6_DOCKER_TESTS=1 pnpm vitest run test/ports/host-sandbox.test.ts
describe.skipIf(process.env.TEAM6_DOCKER_TESTS !== "1")("host sandbox port on real Docker", () => {
  it("runs code with no network and a read-only root filesystem", async () => {
    const provider = new DockerSandboxProvider();
    const { port, stored } = setup(new SandboxSupervisor(provider), [
      "sandbox.execute",
      "artifacts.store",
    ]);
    const source = [
      "const fs=require('node:fs');",
      "let rootWritable=true; try{fs.writeFileSync('/etc/x','1')}catch{rootWritable=false}",
      "fs.writeFileSync('/workspace/ok.txt','1');",
      "const nets=Object.keys(require('node:os').networkInterfaces()).filter(n=>n!=='lo');",
      "console.log(JSON.stringify({rootWritable,nets}))",
    ].join("");
    const result = await port.execute(call({ arguments: { source } }), live());
    expect(result).toMatchObject({ status: "ok", output: { exitCode: 0 } });
    const saved = stored[0] as { bytesBase64: string };
    const output = JSON.parse(Buffer.from(saved.bytesBase64, "base64").toString());
    expect(JSON.parse(output.stdout)).toEqual({ rootWritable: false, nets: [] });
    // The provider keeps one container + volume per agent scope (team6-agent-*); remove with
    // `docker rm -f` / `docker volume rm` after the run.
  }, 180_000);
});
