import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isMain, loadSchemas } from "./lib/schema.mjs";

const supported = new Set([
  "$schema",
  "$id",
  "$ref",
  "$defs",
  "title",
  "description",
  "type",
  "properties",
  "required",
  "additionalProperties",
  "enum",
  "const",
  "items",
  "minItems",
  "maxItems",
  "minLength",
  "maxLength",
  "pattern",
  "format",
  "minimum",
  "maximum",
  "oneOf",
  "anyOf",
  "maxProperties",
  "propertyNames",
]);
export function renderType(schema, definitions = {}, prefix = "Contract") {
  const render = (child) => renderType(child, definitions, prefix);
  for (const key of Object.keys(schema))
    if (!supported.has(key)) throw new Error(`Unsupported schema keyword: ${key}`);
  if (schema.$ref) {
    const match = /^#\/\$defs\/([A-Za-z][A-Za-z0-9]*)$/.exec(schema.$ref);
    if (!match || !Object.hasOwn(definitions, match[1]))
      throw new Error("Reference resolution failed");
    if (Object.keys(schema).some((key) => !["$ref", "description", "title"].includes(key)))
      throw new Error("Reference siblings require explicit intersection support");
    return `${prefix}${match[1]}`;
  }
  if (schema.oneOf || schema.anyOf)
    return `(${(schema.oneOf ?? schema.anyOf).map(render).join(" | ")})`;
  if ("const" in schema) return JSON.stringify(schema.const);
  if (schema.enum) return schema.enum.map((value) => JSON.stringify(value)).join(" | ");
  if (Array.isArray(schema.type))
    return schema.type.map((type) => render({ ...schema, type })).join(" | ");
  switch (schema.type) {
    case "null":
      return "null";
    case "string":
      return "string";
    case "boolean":
      return "boolean";
    case "integer":
    case "number":
      return "number";
    case "array":
      return `Array<${render(schema.items)}>`;
    case "object": {
      if (
        typeof schema.additionalProperties === "object" &&
        !schema.properties &&
        !schema.required &&
        Number.isInteger(schema.maxProperties) &&
        schema.propertyNames?.maxLength
      ) {
        return `{ [key: string]: ${render(schema.additionalProperties)} }`;
      }
      if (schema.additionalProperties !== false) throw new Error("Only closed objects supported");
      const fields = Object.entries(schema.properties ?? {}).map(
        ([name, value]) =>
          `${JSON.stringify(name)}${schema.required?.includes(name) ? "" : "?"}: ${render(value)};`,
      );
      return fields.length === 0 ? "Record<string, never>" : `{ ${fields.join(" ")} }`;
    }
    default:
      throw new Error("Schema has no supported type");
  }
}

export function generateContracts(root, check, selectedNames = []) {
  const schemas = loadSchemas();
  for (const name of selectedNames)
    if (!schemas.some((entry) => entry.name === name) || name === "execution-receipt.schema.json")
      throw new Error(`Unknown public contract selection: ${name}`);
  const selected = new Set(selectedNames);
  const outputs = [];
  for (const { name, schema } of schemas) {
    if (selected.size && !selected.has(name)) continue;
    if (name === "execution-receipt.schema.json") continue;
    if (!/^[A-Z][A-Za-z0-9]+$/.test(schema.title))
      throw new Error("Schema title must be a public type identifier");
    const path = `src/contracts/generated/${name.replace(".schema.json", ".ts")}`;
    const definitions = schema.$defs ?? {};
    const aliases = Object.entries(definitions)
      .map(([key, value]) => {
        if (!/^[A-Za-z][A-Za-z0-9]*$/.test(key)) throw new Error("Invalid definition identifier");
        return `type ${schema.title}${key} = ${renderType(value, definitions, schema.title)};`;
      })
      .join("\n");
    const source = `// Generated from schemas/${name}. Do not edit.\n// Runtime validation is required for bounds, patterns and cross-field semantics.\n${aliases}\nexport type ${schema.title} = ${renderType(schema, definitions, schema.title)};\nexport const ${schema.title}Schema = ${JSON.stringify(schema, null, 2)} as const;\n`;
    const formatted = execFileSync(
      "corepack",
      ["pnpm", "exec", "biome", "format", "--stdin-file-path", path],
      { cwd: root, input: source, encoding: "utf8" },
    );
    if (check) {
      if (readFileSync(resolve(root, path), "utf8") !== formatted)
        throw new Error(`Generated contract drift: ${path}`);
    } else {
      mkdirSync(resolve(root, "src/contracts/generated"), { recursive: true });
      writeFileSync(resolve(root, path), formatted);
    }
    outputs.push(path);
    const reference = `sdk/python/agent_platform/schemas/${name}`;
    const canonical = readFileSync(resolve(root, `schemas/${name}`), "utf8");
    if (check) {
      if (readFileSync(resolve(root, reference), "utf8") !== canonical)
        throw new Error(`Python reference schema drift: ${reference}`);
    } else {
      mkdirSync(resolve(root, "sdk/python/agent_platform/schemas"), { recursive: true });
      writeFileSync(resolve(root, reference), canonical);
    }
  }
  return outputs;
}
if (isMain(import.meta.url)) {
  try {
    const paths = generateContracts(
      fileURLToPath(new URL("../", import.meta.url)),
      process.argv.includes("--check"),
      process.argv
        .slice(2)
        .filter((arg) => arg.startsWith("--schema="))
        .map((arg) => arg.slice("--schema=".length)),
    );
    const scope = process.argv.some((arg) => arg.startsWith("--schema="))
      ? "Selected contracts only (not the full gate). "
      : "";
    console.log(
      `${scope}Public contract generation ${process.argv.includes("--check") ? "verified" : "written"}: ${paths.length} files`,
    );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
