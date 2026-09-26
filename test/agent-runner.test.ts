import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { JsonLineAgentRunner } from "../src/agent-runner.js";

const hasPython = (() => {
  try {
    execFileSync("python3", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

describe("agent runner protocol", () => {
  it("bridges a tool call and returns a Python-compatible JSON result", async () => {
    const child = [
      "const rl=require('node:readline').createInterface({input:process.stdin});",
      "rl.on('line',line=>{const m=JSON.parse(line);",
      "if(m.type==='run')process.stdout.write(JSON.stringify({protocol:'agent-runner.v1',type:'tool_call',request_id:m.request_id,call_id:'call-1',name:'warehouse.list_sources',input:{}})+'\\n');",
      "if(m.type==='tool_result')process.stdout.write(JSON.stringify({protocol:'agent-runner.v1',type:'result',request_id:m.request_id,ok:true,output:{tool:m.output}})+'\\n');});",
    ].join("");
    const runner = new JsonLineAgentRunner({
      command: process.execPath,
      args: ["-e", child],
      onToolCall: async (call) => ({ name: call.name, warehouses: ["sales"] }),
    });

    await expect(
      runner.run(
        {
          requestId: "run-1",
          agentId: "team.python.summary",
          agentVersion: "1.0.0",
          input: { prompt: "list sources" },
          scope: { userId: "u1", spaceId: "s1", runId: "run-1" },
          tools: ["warehouse.list_sources"],
        },
        new AbortController().signal,
      ),
    ).resolves.toEqual({
      tool: { name: "warehouse.list_sources", warehouses: ["sales"] },
    });
  });

  it("does not inherit database or provider secrets into the agent process", async () => {
    const child = [
      "const rl=require('node:readline').createInterface({input:process.stdin});",
      "rl.on('line',line=>{const m=JSON.parse(line);",
      "if(m.type==='run')process.stdout.write(JSON.stringify({protocol:'agent-runner.v1',type:'result',request_id:m.request_id,ok:true,output:{database:process.env.DATABASE_URL||null,model:process.env.MODEL_API_KEY||null,path:Boolean(process.env.PATH)}})+'\\n');});",
    ].join("");
    const runner = new JsonLineAgentRunner({
      command: process.execPath,
      args: ["-e", child],
      env: { DATABASE_URL: "blocked", MODEL_API_KEY: "blocked" },
    });

    await expect(
      runner.run(
        {
          requestId: "secret-run-1",
          agentId: "team.python.secret-check",
          agentVersion: "1.0.0",
          input: {},
          scope: { userId: "u1", spaceId: "s1", runId: "secret-run-1" },
          tools: [],
        },
        new AbortController().signal,
      ),
    ).resolves.toEqual({ database: null, model: null, path: true });
  });

  it.skipIf(!hasPython)("runs the reference Python SDK through the same host bridge", async () => {
    const python = [
      "from agent_platform import AgentManifest, serve",
      "class A:",
      " manifest=AgentManifest(id='team.python.test',version='1.0.0',name='test',description='test',input_schema={'type':'object'},tools=('warehouse.list_sources',))",
      " def run(self,value,context): return {'sources': context.warehouse.list_sources(), 'prompt': value['prompt']}",
      "serve(A())",
    ].join("\n");
    const runner = new JsonLineAgentRunner({
      command: "python3",
      args: ["-c", python],
      env: { PYTHONPATH: resolve("sdk/python") },
      onToolCall: async () => ({ warehouses: [{ id: "sales" }] }),
    });

    await expect(
      runner.run(
        {
          requestId: "python-run-1",
          agentId: "team.python.test",
          agentVersion: "1.0.0",
          input: { prompt: "hello" },
          scope: { userId: "u1", spaceId: "s1", runId: "python-run-1" },
          tools: ["warehouse.list_sources"],
        },
        new AbortController().signal,
      ),
    ).resolves.toEqual({
      sources: { warehouses: [{ id: "sales" }] },
      prompt: "hello",
    });
  });
});
