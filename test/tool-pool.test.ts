import { Type } from "typebox";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type McpPoolTool, McpToolPool } from "../src/tool-pool.js";

const tool: McpPoolTool = {
  name: "records.read",
  description: "Read records",
  schema: Type.Object({ query: Type.String() }),
  mutates: false,
  agents: ["reader"],
  authorize: (scope) => scope.spaceId === "allowed",
  execute: vi.fn(async (input) => ({ result: (input as { query: string }).query })),
};

describe("McpToolPool", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists tools to subscribed agents and rechecks authorization for calls", async () => {
    const pool = new McpToolPool();
    pool.register(tool);
    expect(pool.forAgent("reader").map(({ name }) => name)).toEqual(["records.read"]);
    expect(pool.forAgent("other")).toEqual([]);

    const result = await pool.call(
      "records.read",
      { query: "sales" },
      { userId: "u1", spaceId: "allowed", signal: new AbortController().signal },
      "reader",
    );
    expect(result).toEqual({ result: "sales" });
    await expect(
      pool.call(
        "records.read",
        { query: "sales" },
        { userId: "u1", spaceId: "denied", signal: new AbortController().signal },
        "reader",
      ),
    ).rejects.toThrow("not authorized");
  });

  it("rejects invalid arguments and duplicate registrations", async () => {
    const pool = new McpToolPool();
    pool.register(tool);
    expect(() => pool.register(tool)).toThrow("already registered");
    await expect(
      pool.call(
        "records.read",
        { query: 1 },
        { userId: "u1", spaceId: "allowed", signal: new AbortController().signal },
        "reader",
      ),
    ).rejects.toThrow("Invalid input");
    expect(tool.execute).not.toHaveBeenCalled();
  });
});
