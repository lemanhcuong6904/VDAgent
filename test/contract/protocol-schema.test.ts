import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Ajv2020 } from "ajv/dist/2020.js";
import { fullFormats } from "ajv-formats/dist/formats.js";
import { describe, expect, it } from "vitest";
import {
  AGENT_PROTOCOL,
  type ProtocolMessage,
  parseMessage,
  serializeMessage,
} from "../../src/agent-protocol.js";
import { AgentProtocolSchema } from "../../src/contracts/index.js";

const ajv = new Ajv2020({ strict: true });
ajv.addFormat("date-time", fullFormats["date-time"]);
ajv.addFormat("uri", fullFormats.uri);
const validate = ajv.compile(AgentProtocolSchema);
const protocol = AGENT_PROTOCOL;
const scope = { user_id: "user-1", space_id: "space-1", run_id: "run-1" };

// One frame per message type, shaped by the runtime TypeScript interfaces.
const frames: ProtocolMessage[] = [
  { protocol, type: "hello", version: "2.0.0", capabilities: ["checkpoint"] },
  { protocol, type: "invoke", request_id: "r1", agent_id: "a", input: { q: "x" }, scope },
  {
    protocol,
    type: "port_call",
    request_id: "r1",
    call_id: "c1",
    port: "tools",
    operation: "search",
    input: { q: "x" },
    sequence: 1,
  },
  { protocol, type: "port_result", request_id: "r1", call_id: "c1", ok: true, output: [1, 2] },
  {
    protocol,
    type: "port_result",
    request_id: "r1",
    call_id: "c1",
    ok: false,
    error: { code: "sequence_error", message: "stale", retriable: false },
    sequence: 2,
  },
  { protocol, type: "event", request_id: "r1", event: "progress", data: { pct: 50 } },
  {
    protocol,
    type: "checkpoint",
    request_id: "r1",
    checkpoint_id: "cp1",
    manifest: { id: "cp1", created_at: "2026-09-27T00:00:00.000Z", size_bytes: 10 },
  },
  { protocol, type: "wait", request_id: "r1", wait_for: "child:run-2", timeout_ms: 1000 },
  { protocol, type: "cancel", request_id: "r1", reason: "user" },
  {
    protocol,
    type: "result",
    request_id: "r1",
    ok: true,
    output: "done",
    usage: { input_tokens: 1, output_tokens: 2, total_tokens: 3 },
    artifacts: [{ id: "art1", type: "text/markdown" }],
  },
];

describe("agent-protocol.v2 canonical schema", () => {
  it("accepts every runtime message type after a serialize/parse round trip", () => {
    const types = new Set<string>();
    for (const frame of frames) {
      const parsed = parseMessage(serializeMessage(frame));
      expect(validate(parsed), JSON.stringify(validate.errors)).toBe(true);
      types.add(parsed.type);
    }
    expect(types.size).toBe(9);
  });

  it("rejects wrong protocol, missing correlation and unbounded identifiers", () => {
    expect(validate({ ...frames[1], protocol: "agent-runner.v1" })).toBe(false);
    const { request_id: _omit, ...missing } = frames[2] as unknown as Record<string, unknown>;
    expect(validate(missing)).toBe(false);
    expect(validate({ ...frames[1], request_id: "x".repeat(257) })).toBe(false);
  });

  it("keeps unknown fields at the parser while the schema stays closed", () => {
    const line = JSON.stringify({ ...frames[5], future_field: 1 });
    const parsed = parseMessage(line) as unknown as Record<string, unknown>;
    expect(parsed.future_field).toBe(1);
    expect(validate(parsed)).toBe(false);
  });

  it("validates frames emitted by the Python SDK and ships the same schema resource", () => {
    // Drive the real SDK: invoke -> port_call -> port_result -> result, all over agent-runner.v2.
    const script = `
import io, json
from agent_platform import serve
from agent_platform.contracts import schema
class Agent:
    def run(self, value, ctx):
        return {"echo": ctx.tools.call("echo", {"n": value["n"]})}
invoke = json.dumps({"protocol": "agent-runner.v2", "type": "invoke", "request_id": "r1",
                     "agent_id": "a", "input": {"n": 1}, "scope": {"user_id": "u", "space_id": "s"}})
out = io.StringIO()
class Host:
    """Scripted host: invoke, then answer the SDK's port_call, then close stdin."""
    step = 0
    def readline(self):
        self.step += 1
        if self.step == 1:
            return invoke + "\\n"
        if self.step == 2:
            call = json.loads(out.getvalue().splitlines()[-1])
            return json.dumps({"protocol": "agent-runner.v2", "type": "port_result", "request_id": "r1",
                               "call_id": call["call_id"], "ok": True, "output": {"n": 1}}) + "\\n"
        return ""
serve(Agent(), stdin=Host(), stdout=out)
print(json.dumps({"frames": [json.loads(l) for l in out.getvalue().splitlines()], "schema": schema("agent-protocol")}))
`;
    const output = execFileSync("python3", ["-c", script], {
      env: { ...process.env, PYTHONPATH: resolve("sdk/python") },
      encoding: "utf8",
      timeout: 10000,
    });
    const { frames: emitted, schema } = JSON.parse(output) as {
      frames: Array<{ type: string }>;
      schema: unknown;
    };
    expect(emitted.map((frame) => frame.type)).toEqual(["port_call", "result"]);
    for (const frame of emitted)
      expect(validate(frame), JSON.stringify(validate.errors)).toBe(true);
    expect(schema).toEqual(JSON.parse(readFileSync("schemas/agent-protocol.schema.json", "utf8")));
  });
});
