import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

export const schemaDirectory = new URL("../../schemas/", import.meta.url);
export const dialect = "https://json-schema.org/draft/2020-12/schema";

export function createValidator() {
  const ajv = new Ajv2020({ strict: true, allErrors: true, validateFormats: true });
  addFormats(ajv);
  return ajv;
}

// Repository schemas are trusted code. No remote loading, coercion, defaults or removal.
export function loadSchemas(directory = schemaDirectory) {
  return readdirSync(directory)
    .filter((name) => name.endsWith(".schema.json"))
    .sort()
    .map((name) => ({
      name,
      schema: JSON.parse(readFileSync(new URL(name, directory), "utf8")),
    }));
}

export function schemaConventions(schema) {
  const errors = [];
  if (schema.$schema !== dialect) errors.push("wrong dialect");
  if (!/^urn:team6:schema:[a-z0-9-]+:v[1-9][0-9]*$/.test(schema.$id ?? "")) {
    errors.push("missing versioned schema ID");
  }
  function walk(node, path = "#") {
    if (!node || typeof node !== "object" || Array.isArray(node)) return;
    if (node.$ref && !node.$ref.startsWith("#/$defs/")) errors.push(`${path}: non-local reference`);
    const types = Array.isArray(node.type) ? node.type : [node.type];
    const boundedMap =
      typeof node.additionalProperties === "object" &&
      !node.properties &&
      !node.required &&
      Number.isInteger(node.maxProperties) &&
      node.maxProperties > 0 &&
      Number.isInteger(node.propertyNames?.maxLength);
    if (types.includes("object") && node.additionalProperties !== false && !boundedMap) {
      errors.push(`${path}: object must reject unknown fields`);
    }
    if (types.includes("string") && !node.enum && !Number.isInteger(node.maxLength)) {
      errors.push(`${path}: unbounded string`);
    }
    if (types.includes("array") && !Number.isInteger(node.maxItems)) {
      errors.push(`${path}: unbounded array`);
    }
    if (
      (types.includes("number") || types.includes("integer")) &&
      (!Number.isFinite(node.minimum) || !Number.isFinite(node.maximum))
    ) {
      errors.push(`${path}: unbounded number`);
    }
    for (const key of ["properties", "$defs"]) {
      for (const [name, child] of Object.entries(node[key] ?? {}))
        walk(child, `${path}/${key}/${name}`);
    }
    for (const key of [
      "items",
      "not",
      "if",
      "then",
      "else",
      "additionalProperties",
      "propertyNames",
    ])
      walk(node[key], `${path}/${key}`);
    for (const key of ["allOf", "anyOf", "oneOf", "prefixItems"]) {
      for (const [index, child] of (node[key] ?? []).entries())
        walk(child, `${path}/${key}/${index}`);
    }
  }
  walk(schema);
  return errors;
}

export function isMain(url) {
  return process.argv[1] && fileURLToPath(url) === resolve(process.argv[1]);
}
