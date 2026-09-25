import { describe, expect, it, vi } from "vitest";
import { DockerSandboxProvider } from "../src/docker-sandbox.js";
import { createSandboxTool, type SandboxProvider, selectSandboxProvider } from "../src/sandbox.js";

describe("sandbox provider boundary", () => {
  it("delegates the shared command contract to an offline fake", async () => {
    const execute = vi.fn(async () => ({ exitCode: 0 }));
    const fake: SandboxProvider = { execute };
    const tool = createSandboxTool(fake);
    const scope = {
      userId: "user-a",
      spaceId: "space-a",
      agentId: "agent-a",
      signal: new AbortController().signal,
    };

    await tool.execute({ argv: ["printf", "ok"] }, scope);

    expect(execute).toHaveBeenCalledWith({ argv: ["printf", "ok"] }, scope);
  });

  it("keeps Docker as the execution adapter and none as the disabled mode", async () => {
    const docker = new DockerSandboxProvider();
    expect(selectSandboxProvider("docker", docker)).toBe(docker);
    expect(selectSandboxProvider("none", docker)).toBeUndefined();
    expect(() => selectSandboxProvider("host", docker)).toThrow("Unsupported sandbox provider");
  });
});
