import assert from "node:assert/strict";
import { test } from "node:test";
import { dependencyErrors, packageIdentity } from "../lib/dependencies.mjs";

function fixture() {
  return {
    manifests: [{ dependencies: { example: "1.2.3" } }, { dependencies: { example: "1.2.3" } }],
    backend: {
      lockfileVersion: "9.0",
      importers: {
        ".": { dependencies: { example: { specifier: "1.2.3", version: "1.2.3(peer@1.0.0)" } } },
      },
      packages: { "example@1.2.3": { resolution: { integrity: `sha512-${"a".repeat(86)}==` } } },
    },
    frontend: {
      lockfileVersion: 3,
      packages: {
        "": { dependencies: { example: "1.2.3" } },
        "node_modules/example": { version: "1.2.3", integrity: `sha512-${"a".repeat(86)}==` },
      },
    },
  };
}
test("dependency gate handles lock formats and peer-qualified exact versions", () => {
  assert.deepEqual(dependencyErrors(fixture()), []);
  assert.deepEqual(packageIdentity("@scope/pkg@1.2.3(peer@2.0.0)"), {
    name: "@scope/pkg",
    version: "1.2.3",
  });
});
test("dependency gate rejects version drift, missing packages and integrity", () => {
  for (const mutate of [
    (value) => {
      value.manifests[0].dependencies.example = "^1.2.3";
    },
    (value) => {
      value.backend.importers["."].dependencies.example.version = "1.2.4";
    },
    (value) => {
      delete value.backend.importers["."].dependencies.example;
    },
    (value) => {
      delete value.frontend.packages["node_modules/example"].integrity;
    },
    (value) => {
      delete value.backend.packages["example@1.2.3"].resolution.integrity;
    },
    (value) => {
      value.frontend.lockfileVersion = 2;
    },
  ]) {
    const value = fixture();
    mutate(value);
    assert.ok(dependencyErrors(value).length > 0);
  }
});
