import assert from "node:assert/strict";
import { test } from "node:test";
import { secretFindings } from "../check-secrets.mjs";

test("detects representative credentials without printing their content", () => {
  const samples = [
    ["private-key", ["-----BEGIN", "PRIVATE KEY-----"].join(" ")],
    ["github-token", `ghp_${"a".repeat(36)}`],
    ["aws-access-key", `AKIA${"A".repeat(16)}`],
    ["provider-key", `sk-proj-${"A".repeat(40)}`],
    ["slack-token", `xoxb-${"1".repeat(24)}`],
    ["credential-url", `postgresql://user:${"a".repeat(20)}@localhost/db`],
  ];
  for (const [rule, value] of samples) {
    const findings = secretFindings("example.ts", `\n${value}`);
    assert.ok(findings.some((finding) => finding.rule === rule && finding.line === 2));
    assert.equal(JSON.stringify(findings).includes(value), false);
  }
});

test("does not treat environment-reference templates as credentials", () => {
  assert.deepEqual(
    secretFindings(
      ".env.example",
      ["postgresql://user:", `\${POSTGRES_PASSWORD}`, "@localhost/db"].join(""),
    ),
    [],
  );
  assert.deepEqual(
    secretFindings("README.md", "postgresql://user:<your-password>@localhost/db"),
    [],
  );
});
