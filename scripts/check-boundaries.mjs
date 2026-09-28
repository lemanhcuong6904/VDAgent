import { existsSync, readFileSync, realpathSync } from "node:fs";
import { posix, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { sha256 } from "./lib/receipt.mjs";
import { isMain } from "./lib/schema.mjs";
import { analyzeModule, readSource, repositoryFiles, sourceFile } from "./lib/source.mjs";

const authorities = new Set([
  "process",
  "globalThis",
  "global",
  "fetch",
  "WebSocket",
  "XMLHttpRequest",
  "Worker",
  "Deno",
  "Bun",
  "eval",
  "Function",
  "require",
]);
const isPublic = (path) => path === "src/agent-sdk.ts" || path.startsWith("src/contracts/");
export const checkedSource = (path) =>
  /\.[cm]?[jt]sx?$/.test(path) && (path.startsWith("src/agents/") || isPublic(path));

export function boundaryFindings(path, source, canonicalize = (target) => target) {
  const findings = [];
  const file = sourceFile(path, source);
  const add = (rule, detail, text, line) =>
    findings.push({ file: path, rule, detail, line, fingerprint: sha256(text) });
  for (const edge of analyzeModule(path, source).imports) {
    let allowed = edge.specifier === "typebox" || edge.specifier?.startsWith("typebox/");
    if (edge.specifier?.startsWith(".")) {
      const lexical = posix
        .normalize(posix.join(posix.dirname(path), edge.specifier))
        .replace(/\.(m|c)?js$/, ".$1ts");
      const target = canonicalize(lexical);
      const agentDirectory = posix.dirname(path);
      allowed =
        target !== null &&
        (isPublic(target) ||
          target.startsWith("schemas/") ||
          (!isPublic(path) &&
            agentDirectory !== "src/agents" &&
            target.startsWith(`${agentDirectory}/`)));
    }
    if (!allowed) {
      add(
        edge.specifier === null ? "dynamic-module" : "private-import",
        `${edge.kind}:${edge.specifier ?? "<computed>"}`,
        `${edge.kind}:${edge.specifier ?? "<computed>"}`,
        edge.line,
      );
      findings[findings.length - 1].fingerprint = edge.fingerprint;
    }
  }
  function visit(node) {
    if (ts.isIdentifier(node) && authorities.has(node.text)) {
      // Property names such as ctx.tools.require are not ambient authority references.
      const propertyName = ts.isPropertyAccessExpression(node.parent) && node.parent.name === node;
      if (!propertyName)
        add(
          "ambient-authority",
          node.text,
          node.parent.getText(file),
          file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1,
        );
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return findings;
}

export function reconcileExceptions(findings, exceptions) {
  const remaining = [...exceptions];
  const violations = [];
  const accepted = [];
  for (const finding of findings) {
    const index = remaining.findIndex(
      (entry) =>
        entry.file === finding.file &&
        entry.rule === finding.rule &&
        entry.detail === finding.detail &&
        entry.fingerprint === finding.fingerprint &&
        entry.owner &&
        entry.removeBy &&
        entry.reason,
    );
    if (index < 0) violations.push(finding);
    else accepted.push({ ...finding, exception: remaining.splice(index, 1)[0] });
  }
  return { violations, accepted, staleExceptions: remaining };
}

export function scanBoundaries(root) {
  const paths = repositoryFiles(root).filter(checkedSource);
  const canonicalize = (path) => {
    const candidate = [path, path.replace(/\.ts$/, ".tsx")].find((name) =>
      existsSync(resolve(root, name)),
    );
    if (!candidate) return null;
    const canonical = relative(realpathSync(root), realpathSync(resolve(root, candidate)))
      .split("\\")
      .join("/");
    return canonical.startsWith("../") ? null : canonical;
  };
  const config = JSON.parse(readFileSync(resolve(root, "tsconfig.json"), "utf8"));
  if (config.extends || config.compilerOptions?.paths || config.compilerOptions?.baseUrl) {
    throw new Error("Module resolution configuration changed; boundary resolver review required");
  }
  return paths.flatMap((path) => boundaryFindings(path, readSource(root, path), canonicalize));
}

if (isMain(import.meta.url)) {
  const root = fileURLToPath(new URL("../", import.meta.url));
  try {
    const policy = JSON.parse(
      readFileSync(resolve(root, "scripts/policy/import-exceptions.json"), "utf8"),
    );
    const result = reconcileExceptions(scanBoundaries(root), policy.exceptions);
    for (const finding of result.violations)
      console.error(`${finding.file}:${finding.line}: ${finding.rule} ${finding.detail}`);
    for (const entry of result.staleExceptions)
      console.error(`${entry.file}: stale or invalid exception ${entry.detail}`);
    if (result.violations.length || result.staleExceptions.length) process.exitCode = 1;
    else
      console.log(
        `Import boundary PASS; ${result.accepted.length} explicit legacy debts remain (see policy; not a clean target architecture claim)`,
      );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
