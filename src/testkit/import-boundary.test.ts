/** Run the canonical AST boundary gate; do not duplicate it with permissive regexes. */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

it("enforces repository boundaries with exact, non-stale legacy exceptions", () => {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const output = execFileSync(process.execPath, ["scripts/check-boundaries.mjs"], {
    cwd: root,
    encoding: "utf8",
    timeout: 30_000,
  });
  expect(output).toContain("Import boundary PASS");
}, 30_000); // Spawns the full AST scan; the default 5s budget flakes under parallel load.
