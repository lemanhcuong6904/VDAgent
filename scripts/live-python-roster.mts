#!/usr/bin/env -S pnpm exec tsx
// Live check of the Python reference roster (agents/) through the real PiRuntime.
// Warehouse = mock provider, artifacts in memory, so no database is needed. Only the model key is
// read from .env and never printed. Usage: pnpm exec tsx scripts/live-python-roster.mts [--budget=0.30]
import { readFileSync } from "node:fs";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { AgentRuntime } from "../src/agent-contract.js";
import { createDefaultModelRegistry } from "../src/model-registry.js";
import { PiRuntime } from "../src/pi-runtime.js";
import type { PiSessionStore } from "../src/pi-session-store.js";
import { createPythonRoster } from "../test/support/python-roster.js";

const budget = Number(process.argv.find((arg) => arg.startsWith("--budget="))?.slice(9) ?? "0.30");
if (!(budget > 0 && budget <= 0.3)) throw new Error("--budget must be in (0, 0.30] USD");

if (!process.env.MODEL_API_KEY) {
  const line = readFileSync(".env", "utf8")
    .split("\n")
    .find((entry) => /^(MODEL_API_KEY|OPENAI_API_KEY)=\S/.test(entry));
  if (!line) throw new Error("MODEL_API_KEY/OPENAI_API_KEY not set in .env");
  process.env.MODEL_API_KEY = line.slice(line.indexOf("=") + 1).trim();
}

const sessions: PiSessionStore = {
  async open() {
    return {
      load: async () => ({ messages: [] as AgentMessage[], revision: 0 }),
      save: async () => 1,
      release: async () => undefined,
    };
  },
};
const calls: Array<{ agent: string; model: string; tokens: number; costUsd: number; ms: number }> =
  [];
let spent = 0;
const pi = new PiRuntime(sessions, createDefaultModelRegistry(), undefined, async (record) => {
  spent += record.estimatedCost ?? 0;
  calls.push({
    agent: record.agentId,
    model: `${record.provider}/${record.model}`,
    tokens: (record.inputTokens ?? 0) + (record.outputTokens ?? 0),
    costUsd: record.estimatedCost ?? 0,
    ms: Math.round(record.latencyMs),
  });
});
// Hard stop before any call once the cap is reached.
const runtime = {
  prompt(input: Parameters<PiRuntime["prompt"]>[0]) {
    if (spent >= budget) throw new Error(`Live budget $${budget} reached`);
    return pi.prompt(input);
  },
} as unknown as AgentRuntime;

const cases = [
  "Chào bạn, bạn làm được gì?",
  "Analyze monthly_sales: compare January and February revenue by region, explain the trend, and create a chart report.",
];
const results = [];
for (const prompt of cases) {
  const roster = await createPythonRoster(runtime);
  const started = Date.now();
  const answer = await roster.ask(prompt);
  const cited =
    answer.match(
      /\b(?:ds_(?:[a-zA-Z0-9]{12}|[a-f0-9]{24})|ch_[a-zA-Z0-9]{12}|rp_[a-zA-Z0-9]{12})\b/g,
    ) ?? [];
  const persisted = new Set([
    ...roster.artifacts.datasets.keys(),
    ...roster.artifacts.charts.keys(),
    ...roster.artifacts.reports.keys(),
  ]);
  results.push({
    prompt,
    ms: Date.now() - started,
    invocations: roster.invocations.map(({ agent, status }) => `${agent}:${status}`),
    artifacts: [...persisted],
    citedUnpersisted: cited.filter((id) => !persisted.has(id)),
    reportHeadings: [...roster.artifacts.reports.values()].flatMap(
      ({ markdown }) => markdown.match(/^## .+$/gm) ?? [],
    ),
    answer,
  });
}

console.log(
  JSON.stringify(
    {
      budgetUsd: budget,
      spentUsd: Number(spent.toFixed(6)),
      modelCalls: calls.length,
      byAgent: Object.fromEntries(
        [...new Set(calls.map(({ agent }) => agent))].map((agent) => [
          agent,
          calls.filter((call) => call.agent === agent).length,
        ]),
      ),
      model: calls[0]?.model,
      results,
    },
    null,
    2,
  ),
);
const failed = results.some(
  (r) => r.citedUnpersisted.length || r.invocations.some((i) => i.endsWith(":failed")),
);
process.exit(failed ? 1 : 0);
