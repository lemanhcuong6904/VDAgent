import assert from "node:assert/strict";
import { test } from "node:test";
import { analyzeModule } from "../lib/source.mjs";

test("inventory catches exports and every supported import form without executing source", () => {
  const module = analyzeModule(
    "example.ts",
    `
    import type { Scope } from './contract.js';
    export { Scope } from './contract.js';
    export * as api from './api.js';
    export const { foo, bar } = { foo: 1, bar: 2 };
    export interface Public { field: string }
    export default function () {}
    type Dynamic = import('./types.js').Value;
    import cjs = require('legacy');
    void import(variable);
    require('fs');
  `,
  );
  assert.deepEqual(
    module.imports.map(({ kind }) => kind),
    ["import", "reexport", "reexport", "import-type", "require", "dynamic-import", "require"],
  );
  assert.equal(module.imports[5].specifier, null);
  assert.ok(module.exports.some(({ name }) => name === "Public"));
  assert.ok(module.exports.some(({ name }) => name === "default"));
});

test("inventory distinguishes conditional tests from executed coverage and dynamic registrations", () => {
  const module = analyzeModule(
    "sample.test.ts",
    `
    const integration = describe.skipIf(!databaseUrl);
    it('offline task', () => {});
    registry.register(plugin);
    registry.register('explicit-id');
  `,
  );
  assert.equal(module.conditions[0].condition, "!databaseUrl");
  assert.equal(module.tests[0].title, "offline task");
  assert.deepEqual(
    module.registrations.map(({ literalId }) => literalId),
    [null, "explicit-id"],
  );
  assert.throws(() => analyzeModule("bad.ts", "export const = ;"), /cannot parse/);
});
