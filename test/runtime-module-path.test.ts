import { describe, expect, it } from "vitest";
import { runtimeModuleSpecifier } from "../src/runtime-module-path.js";

describe("compiled runtime module paths", () => {
  it("maps the source warehouse default to emitted JavaScript in production", () => {
    expect(runtimeModuleSpecifier("src/tools/warehouse.ts", true)).toBe("dist/tools/warehouse.js");
  });

  it("maps custom source modules without changing source development", () => {
    expect(runtimeModuleSpecifier("src/tools/custom.ts", true)).toBe("dist/tools/custom.js");
    expect(runtimeModuleSpecifier("src/tools/custom.ts", false)).toBe("src/tools/custom.ts");
  });

  it("leaves emitted, package and file URL specifiers unchanged", () => {
    expect(runtimeModuleSpecifier("dist/tools/warehouse.js", true)).toBe("dist/tools/warehouse.js");
    expect(runtimeModuleSpecifier("file:///tmp/tool.mjs", true)).toBe("file:///tmp/tool.mjs");
  });
});
