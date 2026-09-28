export function testCounts(output) {
  const summary = output.split(/\r?\n/).find((line) => /^\s*Tests\s+/.test(line));
  if (summary) {
    const count = (label) => Number(summary.match(new RegExp(`(\\d+) ${label}\\b`))?.[1] ?? 0);
    return {
      passed: count("passed"),
      failed: count("failed"),
      skipped: count("skipped") + count("todo"),
    };
  }
  const tap = (label) => output.match(new RegExp(`^# ${label} (\\d+)$`, "m"))?.[1];
  if (tap("pass") !== undefined && tap("fail") !== undefined && tap("skipped") !== undefined) {
    return {
      passed: Number(tap("pass")),
      failed: Number(tap("fail")),
      skipped: Number(tap("skipped")) + Number(tap("todo") ?? 0),
    };
  }
  return null;
}

export function classifyGate(result, tests, expectsTests) {
  if (result.error || result.signal)
    return {
      status: "BLOCKED",
      reason: "Command could not finish (spawn, timeout, signal or output limit).",
    };
  if (result.status !== 0 || tests?.failed)
    return { status: "FAIL", reason: "Command or tests failed; inspect bounded output evidence." };
  if (expectsTests && !tests)
    return {
      status: "BLOCKED",
      reason: "Test summary unavailable; cannot verify test coverage from exit code.",
    };
  if (tests && (tests.skipped || !tests.passed))
    return {
      status: "NOT_RUN",
      reason: "Tests skipped or no tests executed; set TEST_DATABASE_URL (pnpm baseline:postgres).",
    };
  return { status: "PASS", reason: "" };
}
