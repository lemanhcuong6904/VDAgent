import assert from "node:assert/strict";
import { test } from "node:test";
import { boundaryFindings, reconcileExceptions } from "../check-boundaries.mjs";

test("agent modules may import public contracts and their own helpers", () => {
  assert.deepEqual(
    boundaryFindings(
      "src/agents/example/index.ts",
      `import { Context } from '../../contracts/index.js'; import './helper.js'; import { Type } from 'typebox';`,
    ),
    [],
  );
});

test("rejects private host, sibling agent and external authority imports including reexports and import types", () => {
  for (const source of [
    `import '../../database.js';`,
    `export * from '../../pi-runtime.js';`,
    `type Pool = import('../../tool-pool.js').Pool;`,
    `import '../other/index.js';`,
    `void import('../../database.js');`,
    `void import(variable);`,
    `import fs from 'node:fs';`,
    `import { Hono } from 'hono';`,
    `import cjs = require('pg');`,
  ])
    assert.ok(boundaryFindings("src/agents/example/index.ts", source).length > 0, source);
});

test("public barrels cannot hide private imports and symlink canonicalization cannot grant access", () => {
  assert.ok(
    boundaryFindings("src/contracts/index.ts", `export * from '../database.js';`).length > 0,
  );
  assert.ok(
    boundaryFindings(
      "src/agents/example/index.ts",
      `import './helper.js';`,
      () => "src/database.ts",
    ).length > 0,
  );
});

test("ambient authority is denied even when aliased or accessed with computed properties", () => {
  for (const source of [
    `const env = process['env'];`,
    `const p = process;`,
    `const { fetch: send } = globalThis;`,
    `eval('1');`,
    `new Function('return 1');`,
  ]) {
    assert.ok(
      boundaryFindings("src/agents/example/index.ts", source).some(
        ({ rule }) => rule === "ambient-authority",
      ),
    );
  }
});

test("legacy exceptions are exact, counted, cannot expand to new files and must be removed when stale", () => {
  const findings = boundaryFindings("src/agents/analytics.ts", `import '../planner.js';`);
  const exception = {
    ...findings[0],
    owner: "Platform",
    removeBy: "M2",
    reason: "Legacy migration",
  };
  assert.equal(reconcileExceptions(findings, [exception]).violations.length, 0);
  assert.equal(reconcileExceptions([...findings, ...findings], [exception]).violations.length, 1);
  assert.equal(
    reconcileExceptions([{ ...findings[0], file: "src/agents/new.ts" }], [exception]).violations
      .length,
    1,
  );
  assert.equal(reconcileExceptions([], [exception]).staleExceptions.length, 1);
});
