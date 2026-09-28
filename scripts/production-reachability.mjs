import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isMain } from "./lib/schema.mjs";

// Static runtime-import reachability from process entry points. Lexical only: dynamic imports,
// plugin loading and configuration flags require runtime verification.
export const matrixPath = "docs/execution/compatibility-matrix.json";
export const entryPoints = ["src/server.ts", "src/worker.ts"];
// Default AGENT_TOOL_MODULES from docker-compose.yml and .env.example; platform-services.ts loads
// it with a runtime import(), which the static closure cannot see. The agent roster is Python
// (agents/manifests) and is outside this TypeScript closure.
export const configuredModules = ["src/tools/warehouse.ts"];
export const groups = [
  ["M1", "public contracts", ["src/contracts/"]],
  ["M1", "contract testkit (test-only by design)", ["src/testkit/"]],
  [
    "M2",
    "host port factory, module adapter and legacy bridge",
    ["src/ports/host-factory.ts", "src/ports/module-plugin.ts", "src/ports/legacy-bridge.ts"],
  ],
  ["M3", "registry, policy and model profiles", ["src/registry/"]],
  ["M4", "ToolPort and MCP adapter", ["src/ports/tool-port.ts", "src/ports/mcp-adapter.ts"]],
  ["M5", "workflow module and plan validator", ["src/workflow/"]],
  [
    "M6",
    "event outbox, collaboration and mailbox",
    ["src/event-outbox.ts", "src/ports/collaboration-port.ts", "src/ports/mailbox.ts"],
  ],
  [
    "M7",
    "session tree, budget and compaction",
    [
      "src/session/session-tree.ts",
      "src/session/context-budget.ts",
      "src/session/compaction-coordinator.ts",
      "src/session/blob-externalizer.ts",
    ],
  ],
  ["M8", "memory provider", ["src/session/memory-provider.ts"]],
  [
    "M9",
    "process protocol, checkpoints and sandbox policy",
    [
      "src/agent-protocol.ts",
      "src/agent-runner.ts",
      "src/checkpoint-manifest.ts",
      "src/sandbox-policy.ts",
    ],
  ],
  [
    "M11",
    "artifacts, evidence, receipts and telemetry",
    [
      "src/artifact-storage.ts",
      "src/evidence-storage.ts",
      "src/terminal-receipt-storage.ts",
      "src/otel-observability.ts",
      "src/observatory.ts",
    ],
  ],
  ["M11", "alert evaluation", ["src/alerts.ts"]],
  [
    "M12",
    "versioned API, MCP server and A2A gateway",
    ["src/platform-api.ts", "src/mcp-server.ts", "src/a2a-gateway.ts"],
  ],
  ["M13", "process lifecycle and readiness", ["src/lifecycle.ts"]],
  ["legacy", "AgentPlugin roster and tool pool", ["src/registry.ts", "src/tool-pool.ts"]],
];

export function buildMatrix(root) {
  const inventory = JSON.parse(
    readFileSync(resolve(root, "docs/execution/inventory.json"), "utf8"),
  );
  const modules = new Map(inventory.modules.map((module) => [module.path, module]));
  const target = (from, specifier) => {
    if (!specifier.startsWith(".")) return undefined;
    const base = normalize(join(dirname(from), specifier)).replace(/\.js$/, "");
    return [`${base}.ts`, `${base}.tsx`, `${base}/index.ts`, base].find((path) =>
      modules.has(path),
    );
  };
  const reachable = new Set();
  const queue = [...entryPoints, ...configuredModules];
  while (queue.length) {
    const path = queue.pop();
    if (reachable.has(path) || !modules.has(path)) continue;
    reachable.add(path);
    for (const edge of modules.get(path).imports ?? []) {
      if (/type/i.test(edge.kind ?? "")) continue; // Type-only edges do not wire runtime behavior.
      const next = target(path, edge.specifier ?? "");
      if (next) queue.push(next);
    }
  }
  const rows = groups.map(([milestone, name, prefixes]) => {
    const files = inventory.modules
      .map((module) => module.path)
      .filter((path) => !/\.test\.[cm]?[jt]sx?$/.test(path))
      .filter((path) => prefixes.some((prefix) => path === prefix || path.startsWith(prefix)));
    const wired = files.filter((path) => reachable.has(path));
    return {
      milestone,
      name,
      files: files.length,
      productionReachable: wired.length,
      status: files.length === 0 ? "MISSING" : wired.length ? "WIRED" : "LIBRARY_ONLY",
    };
  });
  return {
    matrixVersion: "compatibility-matrix.v1",
    method:
      "Static runtime-import closure from process entry points plus default configured plugin/tool modules, over docs/execution/inventory.json; type-only imports excluded.",
    entryPoints,
    configuredModules,
    reachableModules: reachable.size,
    rows,
    limitations: [
      "LIBRARY_ONLY means tested code that production entry points do not import; it is not a runtime failure.",
      "Dynamic imports, external plugin loading and feature flags are not modeled.",
      "WIRED means imported, not that every code path is exercised in production.",
    ],
  };
}

if (isMain(import.meta.url)) {
  const root = fileURLToPath(new URL("../", import.meta.url));
  const matrix = buildMatrix(root);
  for (const row of matrix.rows)
    console.log(
      `${row.status.padEnd(12)} ${row.milestone.padEnd(6)} ${row.name} (${row.productionReachable}/${row.files})`,
    );
  if (process.argv.includes("--write")) {
    const formatted = execFileSync(
      "corepack",
      ["pnpm", "exec", "biome", "format", "--stdin-file-path", matrixPath],
      { cwd: root, input: `${JSON.stringify(matrix, null, 2)}\n`, encoding: "utf8" },
    );
    writeFileSync(resolve(root, matrixPath), formatted);
    console.log(`Wrote ${matrixPath}`);
  }
}
