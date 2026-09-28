import { fileURLToPath } from "node:url";
import { readBoundedFile } from "./lib/receipt.mjs";
import { isMain } from "./lib/schema.mjs";
import { repositoryFiles } from "./lib/source.mjs";

// High-confidence offline patterns only. Findings never include matched values.
const patterns = [
  ["private-key", /-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----/g],
  ["github-token", /\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255})\b/g],
  ["aws-access-key", /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g],
  ["provider-key", /\bsk-(?:proj-|ant-api\d{2}-)?[A-Za-z0-9_-]{32,255}\b/g],
  ["slack-token", /\bxox[baprs]-[A-Za-z0-9-]{20,255}\b/g],
  [
    "credential-url",
    /\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|https?):\/\/[^\s/:@]+:([^\s/@]{12,})@/g,
  ],
];
export function secretFindings(path, source) {
  const findings = [];
  for (const [rule, pattern] of patterns) {
    for (const match of source.matchAll(pattern)) {
      if (rule === "credential-url" && /^(?:\$\{[^}]+\}|<[^>]+>|YOUR_[A-Z_]+)$/.test(match[1]))
        continue;
      if (
        rule === "credential-url" &&
        path === ".env.example" &&
        /^replace-with-[a-z-]+$/.test(match[1])
      )
        continue;
      findings.push({ file: path, rule, line: source.slice(0, match.index).split("\n").length });
    }
  }
  return findings;
}
export function scanSecrets(root) {
  const findings = [];
  let scanned = 0;
  for (const path of repositoryFiles(root)) {
    if (/^(.+\/)?\.env(?:\.(?!example$).+)?$/.test(path)) {
      findings.push({ file: path, rule: "tracked-environment-file", line: 1 });
      continue; // Never open a credential-bearing .env file.
    }
    const bytes = readBoundedFile(root, path);
    if (bytes.includes(0)) continue; // Binary content is outside this text scanner's scope.
    scanned++;
    findings.push(...secretFindings(path, bytes.toString("utf8")));
  }
  return { scanned, findings };
}
if (isMain(import.meta.url)) {
  try {
    const result = scanSecrets(fileURLToPath(new URL("../", import.meta.url)));
    for (const finding of result.findings)
      console.error(`${finding.file}:${finding.line}: ${finding.rule} [REDACTED]`);
    if (result.findings.length) process.exitCode = 1;
    else
      console.log(
        `Secret pattern scan PASS (${result.scanned} text files; ignored files/history/binaries are not scanned)`,
      );
  } catch {
    console.error("Secret scan could not read the full bounded input set; no PASS claimed");
    process.exitCode = 1;
  }
}
