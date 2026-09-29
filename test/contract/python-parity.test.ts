import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Python reference contract parity", () => {
  it("loads the same canonical schemas through Python package resources", () => {
    const names = [
      "agent-event",
      "execution-limits",
      "agent-manifest",
      "agent-result",
      "agent-scope",
      "artifact-ref",
      "checkpoint-ref",
      "evidence-ref",
      "structured-error",
      "usage-summary",
      "wait-request",
      "port-call",
      "port-result",
    ];
    const output = execFileSync(
      "python3",
      [
        "-c",
        "import json; from agent_platform.contracts import schema; import sys; print(json.dumps({name: schema(name) for name in json.loads(sys.argv[1])}))",
        JSON.stringify(names),
      ],
      {
        env: { ...process.env, PYTHONPATH: resolve("sdk/python") },
        encoding: "utf8",
        timeout: 10000,
      },
    );
    const references = JSON.parse(output);
    for (const name of names)
      expect(references[name]).toEqual(
        JSON.parse(readFileSync(`schemas/${name}.schema.json`, "utf8")),
      );
  });
  it("rejects arbitrary resource paths and returns fresh schema instances", () => {
    execFileSync(
      "python3",
      [
        "-c",
        `from agent_platform.contracts import schema
first = schema('agent-scope')
first['properties'].clear()
assert schema('agent-scope')['properties']
try:
    schema('../protocol.py')
except ValueError:
    pass
else:
    raise AssertionError('arbitrary resource allowed')
`,
      ],
      { env: { ...process.env, PYTHONPATH: resolve("sdk/python") }, timeout: 10000 },
    );
  });
});
