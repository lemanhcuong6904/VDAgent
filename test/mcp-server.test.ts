/**
 * MCP server contract - M12.4
 * Driven over real JSON-RPC through the SDK transport with a real McpToolPool, so
 * the tests exercise the same path an agent's MCP client takes.
 */

import { Type } from "typebox";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import {
  CONTRACT_URI,
  classifyToolError,
  encodeBounded,
  handleMcpRequest,
  MCP_CONTRACT_VERSION,
  type McpRequestInput,
  SELF_URI,
} from "../src/mcp-server.js";
import { type McpPoolTool, McpToolPool } from "../src/tool-pool.js";

function tool(overrides: Partial<McpPoolTool>): McpPoolTool {
  return {
    name: "echo",
    description: "Echo input",
    schema: Type.Object({ value: Type.String() }),
    mutates: false,
    agents: ["analytics"],
    authorize: () => true,
    execute: async (input) => input,
    ...overrides,
  };
}

function pool(...tools: McpPoolTool[]) {
  const result = new McpToolPool();
  for (const entry of tools) result.register(entry);
  return result;
}

let nextId = 1;

async function rpc(
  method: string,
  params: Record<string, unknown>,
  input: Partial<McpRequestInput> & { pool: McpToolPool },
  headers: Record<string, string> = {},
) {
  const request = new Request("http://localhost/mcp", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "mcp-protocol-version": "2025-06-18",
      ...headers,
    },
    body: JSON.stringify({ jsonrpc: "2.0", id: nextId++, method, params }),
  });
  const response = await handleMcpRequest(request, {
    agentId: "analytics",
    userId: "user_1",
    spaceId: "space_a",
    allowedTools: ["echo", "big", "boom", "secret"],
    ...input,
  });
  const text = await response.text();
  return { status: response.status, body: text ? JSON.parse(text) : undefined };
}

describe("MCP contract - tools", () => {
  it("lists only tools the pool, the manifest and the descriptor all allow", async () => {
    const tools = pool(
      tool({}),
      tool({ name: "secret", agents: ["other-agent"] }),
      tool({ name: "boom", mutates: true }),
    );
    const { body } = await rpc("tools/list", {}, { pool: tools, allowedTools: ["echo", "secret"] });
    const names = body.result.tools.map((entry: { name: string }) => entry.name);
    // `secret` is allowed by the descriptor but declared for another agent; `boom` the reverse.
    expect(names).toEqual(["echo"]);
  });

  it("annotates mutating tools as destructive", async () => {
    const { body } = await rpc(
      "tools/list",
      {},
      { pool: pool(tool({ name: "boom", mutates: true })) },
    );
    expect(body.result.tools[0].annotations).toEqual({
      readOnlyHint: false,
      destructiveHint: true,
    });
  });

  it("returns text and structured content for an object result", async () => {
    const { body } = await rpc(
      "tools/call",
      { name: "echo", arguments: { value: "hi" } },
      { pool: pool(tool({})) },
    );
    expect(body.result.isError).toBeUndefined();
    expect(JSON.parse(body.result.content[0].text)).toEqual({ value: "hi" });
    expect(body.result.structuredContent).toEqual({ value: "hi" });
  });

  it("refuses a tool outside the agent's grant with a stable code", async () => {
    const { body } = await rpc(
      "tools/call",
      { name: "secret", arguments: { value: "x" } },
      { pool: pool(tool({ name: "secret", agents: ["other-agent"] })) },
    );
    expect(body.result.isError).toBe(true);
    expect(body.result.structuredContent.error.code).toBe("not_authorized");
  });

  it("does not run a tool whose authorize() refuses the scope", async () => {
    const execute = vi.fn(async () => ({}));
    const { body } = await rpc(
      "tools/call",
      { name: "echo", arguments: { value: "x" } },
      { pool: pool(tool({ authorize: (scope) => scope.spaceId === "space_b", execute })) },
    );
    expect(body.result.structuredContent.error.code).toBe("not_authorized");
    expect(execute).not.toHaveBeenCalled();
  });

  it("rejects schema-invalid arguments before execution", async () => {
    const execute = vi.fn(async () => ({}));
    const { body } = await rpc(
      "tools/call",
      { name: "echo", arguments: { value: 42 } },
      { pool: pool(tool({ execute })) },
    );
    expect(body.result.structuredContent.error.code).toBe("invalid_input");
    expect(execute).not.toHaveBeenCalled();
  });

  it("never forwards exception text from a failing tool", async () => {
    const { body } = await rpc(
      "tools/call",
      { name: "boom", arguments: { value: "x" } },
      {
        pool: pool(
          tool({
            name: "boom",
            execute: async () => {
              throw new Error("connect ECONNREFUSED 10.0.0.7:5432 password=hunter2");
            },
          }),
        ),
      },
    );
    expect(body.result.structuredContent.error.code).toBe("tool_failed");
    expect(JSON.stringify(body)).not.toMatch(/hunter2|10\.0\.0\.7|ECONNREFUSED/);
  });

  it("refuses a result over the contract size limit instead of truncating it", async () => {
    const { body } = await rpc(
      "tools/call",
      { name: "big", arguments: { value: "x" } },
      {
        pool: pool(tool({ name: "big", execute: async () => ({ blob: "x".repeat(5_000) }) })),
        maxResultBytes: 1_000,
      },
    );
    expect(body.result.isError).toBe(true);
    expect(body.result.structuredContent.error.code).toBe("result_too_large");
    expect(JSON.stringify(body)).not.toContain("xxxxxxxxxx");
  });
});

describe("MCP contract - resources", () => {
  it("lists the contract and self resources for the assistant audience", async () => {
    const { body } = await rpc("resources/list", {}, { pool: pool(tool({})) });
    expect(body.result.resources.map((entry: { uri: string }) => entry.uri)).toEqual([
      CONTRACT_URI,
      SELF_URI,
    ]);
    for (const entry of body.result.resources)
      expect(entry.annotations.audience).toEqual(["assistant"]);
  });

  it("publishes version, limits, scope and error codes in the contract", async () => {
    const { body } = await rpc(
      "resources/read",
      { uri: CONTRACT_URI },
      { pool: pool(tool({})), maxResultBytes: 4096 },
    );
    const contract = JSON.parse(body.result.contents[0].text);
    expect(contract).toMatchObject({
      contract_version: MCP_CONTRACT_VERSION,
      scope: { user_id: "user_1", space_id: "space_a", agent_id: "analytics" },
      limits: { max_result_bytes: 4096 },
      tools: ["echo"],
    });
    expect(contract.protocol_versions).toContain("2025-06-18");
    expect(contract.error_codes).toContain("result_too_large");
  });

  it("exposes the calling agent's own descriptor only", async () => {
    const { body } = await rpc(
      "resources/read",
      { uri: SELF_URI },
      { pool: pool(tool({})), descriptor: { id: "analytics", version: "1.2.0" } },
    );
    expect(JSON.parse(body.result.contents[0].text)).toEqual({ id: "analytics", version: "1.2.0" });
  });

  it("offers the run template only when a run reader is configured", async () => {
    const without = await rpc("resources/templates/list", {}, { pool: pool(tool({})) });
    expect(without.body.result.resourceTemplates).toEqual([]);
    const withReader = await rpc(
      "resources/templates/list",
      {},
      { pool: pool(tool({})), runs: { read: async () => null } },
    );
    expect(withReader.body.result.resourceTemplates[0].uriTemplate).toBe("platform://runs/{runId}");
  });

  it("passes the full request scope to the run reader", async () => {
    const read = vi.fn(async () => ({ run: { id: "run_1" } }));
    const { body } = await rpc(
      "resources/read",
      { uri: "platform://runs/run_1" },
      { pool: pool(tool({})), runs: { read } },
    );
    expect(read).toHaveBeenCalledWith("run_1", {
      userId: "user_1",
      spaceId: "space_a",
      agentId: "analytics",
    });
    expect(JSON.parse(body.result.contents[0].text)).toEqual({ run: { id: "run_1" } });
  });

  it("answers an out-of-scope run exactly like an unknown resource", async () => {
    const outOfScope = await rpc(
      "resources/read",
      { uri: "platform://runs/run_other" },
      { pool: pool(tool({})), runs: { read: async () => null } },
    );
    const unknown = await rpc(
      "resources/read",
      { uri: "platform://nope" },
      { pool: pool(tool({})) },
    );
    expect(outOfScope.body.error).toEqual(unknown.body.error);
    expect(outOfScope.body.error.message).toContain("Resource not found");
  });

  it("rejects a malformed run id without calling the reader", async () => {
    const read = vi.fn(async () => ({}));
    const { body } = await rpc(
      "resources/read",
      { uri: "platform://runs/../../etc/passwd" },
      { pool: pool(tool({})), runs: { read } },
    );
    expect(body.error).toBeDefined();
    expect(read).not.toHaveBeenCalled();
  });

  it("refuses an oversized resource body", async () => {
    const { body } = await rpc(
      "resources/read",
      { uri: SELF_URI },
      { pool: pool(tool({})), descriptor: { blob: "x".repeat(5_000) }, maxResultBytes: 500 },
    );
    expect(body.error).toBeDefined();
    expect(JSON.stringify(body)).not.toContain("xxxxxxxxxx");
  });
});

describe("MCP contract - transport", () => {
  it("refuses a browser origin that is not allowlisted", async () => {
    const execute = vi.fn(async () => ({}));
    const { status } = await rpc(
      "tools/call",
      { name: "echo", arguments: { value: "x" } },
      { pool: pool(tool({ execute })) },
      { origin: "https://evil.example" },
    );
    expect(status).toBe(403);
    expect(execute).not.toHaveBeenCalled();
  });

  it("accepts an allowlisted origin and a server-to-server call with none", async () => {
    const allowed = await rpc(
      "tools/list",
      {},
      { pool: pool(tool({})), allowedOrigins: ["https://ops.example"] },
      {
        origin: "https://ops.example",
      },
    );
    expect(allowed.status).toBe(200);
    const serverToServer = await rpc("tools/list", {}, { pool: pool(tool({})) });
    expect(serverToServer.status).toBe(200);
  });
});

describe("MCP helpers", () => {
  it("classifies pool errors into stable codes", () => {
    expect(classifyToolError(new Error("Tool 'x' is not authorized for agent 'y'"))).toBe(
      "not_authorized",
    );
    expect(classifyToolError(new Error("Invalid input for tool 'x'"))).toBe("invalid_input");
    expect(classifyToolError(new Error("Tool timed out"))).toBe("timeout");
    expect(classifyToolError(new Error("Tool result must be JSON and at most 1 MB"))).toBe(
      "result_too_large",
    );
    expect(classifyToolError(new Error("anything else"))).toBe("tool_failed");
  });

  it("measures the exact encoded bytes, including multi-byte characters", () => {
    // 9 characters but 10 UTF-8 bytes: a character count would wrongly accept a 9-byte limit.
    expect(encodeBounded({ a: "é" }, 10)).toEqual({ text: '{"a":"é"}' });
    expect(encodeBounded({ a: "é" }, 9)).toEqual({ tooLarge: 10 });
  });
});

const databaseUrl = process.env.TEST_DATABASE_URL;

describe.skipIf(!databaseUrl)("MCP run reader - M12.4 (PostgreSQL)", () => {
  const suffix = Math.random().toString(36).slice(2, 10);
  const runId = `run_mcp_${suffix}`;
  const spaceId = `space_${suffix}`;
  let database: import("pg").Pool;
  let reader: import("../src/mcp-run-reader.js").ParticipatingRunReader;

  beforeAll(async () => {
    const { Pool } = await import("pg");
    const { migrateDatabase } = await import("../src/database.js");
    const { ParticipatingRunReader } = await import("../src/mcp-run-reader.js");
    database = new Pool({ connectionString: databaseUrl, max: 4 });
    await migrateDatabase(database);
    await database.query(
      `INSERT INTO platform_runs (id, space_id, user_id, workflow_id, workflow_version, status, idempotency_key)
       VALUES ($1, $2, 'user_1', 'analytics', '1.0.0', 'running', $1)`,
      [runId, spaceId],
    );
    await database.query(
      `INSERT INTO platform_run_steps (id, run_id, kind, agent_id, status, input)
       VALUES ($1, $2, 'agent', 'analytics', 'running', '{"prompt":"private"}'::jsonb)`,
      [`step_${suffix}`, runId],
    );
    reader = new ParticipatingRunReader(database);
  });

  afterAll(async () => {
    await database?.query("DELETE FROM platform_runs WHERE id = $1", [runId]);
    await database?.end();
  });

  it("returns the projection to an agent that ran a step, without step bodies", async () => {
    const run = (await reader.read(runId, { userId: "user_1", spaceId, agentId: "analytics" })) as {
      run: { id: string };
    } | null;
    expect(run?.run.id).toBe(runId);
    expect(JSON.stringify(run)).not.toContain("private");
  });

  it("refuses an agent in the same space that took no part in the run", async () => {
    await expect(
      reader.read(runId, { userId: "user_1", spaceId, agentId: "visualize" }),
    ).resolves.toBeNull();
  });

  it("refuses the participating agent under another user or space", async () => {
    await expect(
      reader.read(runId, { userId: "user_2", spaceId, agentId: "analytics" }),
    ).resolves.toBeNull();
    await expect(
      reader.read(runId, { userId: "user_1", spaceId: "other-space", agentId: "analytics" }),
    ).resolves.toBeNull();
  });
});
