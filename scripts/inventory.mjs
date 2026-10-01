import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { fileEvidence } from "./lib/receipt.mjs";
import { isMain } from "./lib/schema.mjs";
import { analyzeModule, readSource, repositoryFiles } from "./lib/source.mjs";

export const inventoryPath = "docs/execution/inventory.json";
export function buildInventory(root) {
  const paths = repositoryFiles(root).filter(
    (path) => !path.startsWith("docs/execution/") || path.endsWith(".md"),
  );
  const modulePaths = paths.filter(
    (path) => /^(src|frontend\/src|test)\//.test(path) && /\.[cm]?[jt]sx?$/.test(path),
  );
  const modules = modulePaths.map((path) => ({
    ...fileEvidence(root, path),
    ...analyzeModule(path, readSource(root, path)),
  }));
  const sqlPaths = paths.filter((path) => /^db\/migrations\/.*\.sql$/.test(path));
  const migrations = sqlPaths.map((path) => {
    const source = readSource(root, path);
    return {
      ...fileEvidence(root, path),
      tables: [
        ...source.matchAll(/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z_0-9]*)/gi),
      ].map((match) => ({ name: match[1], line: source.slice(0, match.index).split("\n").length })),
    };
  });
  const python = paths
    .filter((path) => path.startsWith("sdk/python/") && path.endsWith(".py"))
    .map((path) => ({
      ...fileEvidence(root, path),
      declarations: [
        ...readSource(root, path).matchAll(/^(?:class|(?:async\s+)?def)\s+(\w+)/gm),
      ].map((match) => match[1]),
    }));
  return {
    inventoryVersion: "inventory.v1",
    method:
      "TypeScript AST; SQL CREATE TABLE and Python top-level declarations are lexical inventories, not executed registries or coverage.",
    files: paths
      .filter((path) => /^(src\/|frontend\/src\/|db\/|sdk\/|docs\/)|\.md$/.test(path))
      .map((path) => fileEvidence(root, path)),
    modules,
    migrations,
    bootstrapTables: [{ source: "src/database.ts", name: "schema_migrations" }],
    python,
    testFiles: modulePaths.filter((path) => /\.(test|spec)\.[cm]?[jt]sx?$/.test(path)),
    limitations: [
      "Dynamic registration values and generated test cases require runtime verification.",
      "Test presence and import edges do not prove behavioral coverage.",
      "Ignored files, credentials, generated execution captures, build outputs and dependencies are excluded.",
    ],
  };
}

if (isMain(import.meta.url)) {
  const root = fileURLToPath(new URL("../", import.meta.url));
  try {
    const inventory = buildInventory(root);
    if (process.argv.includes("--write")) {
      // Match the repository formatter so `pnpm lint` stays clean after regeneration.
      const formatted = execFileSync(
        "corepack",
        ["pnpm", "exec", "biome", "format", "--stdin-file-path", inventoryPath],
        { cwd: root, input: `${JSON.stringify(inventory, null, 2)}\n`, encoding: "utf8" },
      );
      writeFileSync(resolve(root, inventoryPath), formatted);
      console.log(`Wrote ${inventoryPath}`);
    } else {
      const saved = JSON.parse(readFileSync(resolve(root, inventoryPath), "utf8"));
      if (JSON.stringify(saved) !== JSON.stringify(inventory))
        throw new Error("Inventory stale; run pnpm inventory:write and review changes");
      console.log(
        `Inventory matches ${inventory.modules.length} modules, ${inventory.migrations.length} migrations and ${inventory.testFiles.length} test files`,
      );
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
