import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { validateReceipt } from "./lib/receipt.mjs";
import { isMain } from "./lib/schema.mjs";

// M14.5: per-milestone evidence audit. A milestone is VERIFIED only with a valid execution.v1
// milestone receipt carrying reviewer, artifact hashes, limitations and a PASS rollback.
export const auditPath = "docs/execution/milestone-audit.json";

export function auditMilestones(root) {
  const plan = readFileSync(resolve(root, "PLAN.md"), "utf8");
  const matrix = JSON.parse(
    readFileSync(resolve(root, "docs/execution/compatibility-matrix.json"), "utf8"),
  );
  const receiptsDir = resolve(root, "docs/execution/receipts");
  const receipts = readdirSync(receiptsDir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => {
      const path = `docs/execution/receipts/${name}`;
      let receipt;
      try {
        receipt = JSON.parse(readFileSync(resolve(root, path), "utf8"));
      } catch {
        return { path, errors: ["invalid JSON"] };
      }
      const errors = validateReceipt(receipt, { root });
      return { path, receipt, errors };
    });
  const rows = [];
  for (let n = 0; n <= 14; n++) {
    const id = `M${n}`;
    const items = [...plan.matchAll(new RegExp(`^- \\[(.)\\] ${id}\\.\\d+`, "gm"))].map(
      (m) => m[1],
    );
    const own = receipts.filter(({ path }) => new RegExp(`/${id}[-.]`).test(path));
    const milestone = own.find(
      ({ receipt, errors }) =>
        receipt?.kind === "milestone" && receipt.status === "PASS" && errors.length === 0,
    );
    const other = own.filter(({ errors }) => errors.length === 0).map(({ path }) => path);
    const wiring = matrix.rows.filter((row) => row.milestone === id).map((row) => row.status);
    const gaps = [];
    if (!milestone) gaps.push("no valid execution.v1 milestone receipt (reviewer + rollback PASS)");
    if (items.some((mark) => mark !== "x"))
      gaps.push(`${items.filter((m) => m !== "x").length} checklist item(s) not [x]`);
    // M1 PASS is "independently testable"; production wiring is judged from M2 onward.
    if (n >= 2 && wiring.includes("LIBRARY_ONLY"))
      gaps.push("contract code not reachable from production entry points");
    rows.push({
      milestone: id,
      checklist: `${items.filter((mark) => mark === "x").length}/${items.length}`,
      receipt: milestone?.path ?? null,
      reviewer: milestone?.receipt.reviewer ?? null,
      rollback: milestone?.receipt.rollback.status ?? null,
      artifacts: milestone?.receipt.artifacts.length ?? 0,
      otherValidReceipts: other.filter((path) => path !== milestone?.path),
      status: gaps.length ? "UNVERIFIED" : "VERIFIED",
      gaps,
    });
  }
  const invalid = receipts
    .filter(({ errors }) => errors.length)
    .map(({ path, errors }) => ({ path, reason: errors[0] }));
  return {
    auditVersion: "milestone-audit.v1",
    method:
      "PLAN.md checklist marks, execution.v1 receipt validation (hashes re-verified) and compatibility-matrix wiring.",
    rows,
    invalidReceipts: invalid,
    limitations: [
      "Self-review receipts are technical evidence, not human approval (M14.7).",
      "UNVERIFIED means evidence is missing or incomplete, not that behavior is broken.",
    ],
  };
}

if (isMain(import.meta.url)) {
  const root = fileURLToPath(new URL("../", import.meta.url));
  const audit = auditMilestones(root);
  for (const row of audit.rows)
    console.log(
      `${row.status.padEnd(10)} ${row.milestone.padEnd(4)} ${row.checklist.padEnd(5)} ${row.gaps.join("; ")}`,
    );
  for (const entry of audit.invalidReceipts)
    console.log(`invalid receipt ${entry.path}: ${entry.reason}`);
  if (process.argv.includes("--write")) {
    const formatted = execFileSync(
      "corepack",
      ["pnpm", "exec", "biome", "format", "--stdin-file-path", auditPath],
      { cwd: root, input: `${JSON.stringify(audit, null, 2)}\n`, encoding: "utf8" },
    );
    writeFileSync(resolve(root, auditPath), formatted);
    console.log(`Wrote ${auditPath}`);
  }
}
