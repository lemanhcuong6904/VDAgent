import { fileURLToPath } from "node:url";
import { readBoundedFile, validateReceipt } from "./lib/receipt.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const args = process.argv.slice(2);
const verifyInputs = args.includes("--current-inputs");
const paths = args.filter((arg) => arg !== "--current-inputs");
if (paths.length === 0) {
  console.error("Usage: node scripts/validate-receipt.mjs [--current-inputs] <receipt.json> ...");
  process.exitCode = 1;
}
for (const path of paths) {
  try {
    const receipt = JSON.parse(readBoundedFile(root, path).toString("utf8"));
    const errors = validateReceipt(receipt, { root, verifyInputs });
    if (errors.length) throw new Error(errors.join("; "));
    console.log(
      `${path}: valid ${receipt.kind} receipt (${receipt.status}); not a release approval`,
    );
  } catch (error) {
    console.error(`${path}: ${error instanceof SyntaxError ? "invalid JSON" : error.message}`);
    process.exitCode = 1;
  }
}
