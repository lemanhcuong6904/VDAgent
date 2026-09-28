import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  dependencyErrors,
  dependencySources,
  frontendLicenses,
  installedLicenses,
  packageIdentity,
  readJson,
} from "./lib/dependencies.mjs";
import { fileEvidence } from "./lib/receipt.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
try {
  const sources = dependencySources(root);
  const errors = dependencyErrors(sources);
  const policy = readJson(root, "scripts/policy/licenses.json");
  const known = new Map([...frontendLicenses(sources.frontend), ...installedLicenses(root)]);
  const supplemental = readJson(root, "scripts/policy/registry-license-metadata.json");
  for (const entry of supplemental.records) {
    const key = `${entry.name}@${entry.version}`;
    if (sources.backend.packages[key]?.resolution.integrity !== entry.integrity)
      errors.push(`${key}: supplemental license artifact mismatch`);
    else known.set(key, entry.license);
  }
  const components = [];
  const relationships = [];
  const checkLicense = (name, license) => {
    if (!policy.knownExpressions.includes(license))
      errors.push(`${name}: missing or unreviewed license expression`);
  };
  for (const [key, entry] of Object.entries(sources.backend.packages).sort()) {
    const license = known.get(key) ?? null;
    checkLicense(key, license);
    components.push({
      id: `pnpm:${key}`,
      ...packageIdentity(key),
      integrity: entry.resolution.integrity,
      license,
      scope: "backend-lock",
      optional: Boolean(entry.optional),
    });
  }
  for (const [key, snapshot] of Object.entries(sources.backend.snapshots).sort()) {
    const from = `pnpm:${key.split("(")[0]}`;
    for (const kind of ["dependencies", "optionalDependencies"]) {
      for (const [name, version] of Object.entries(snapshot[kind] ?? {}).sort()) {
        const to = `pnpm:${name}@${version.split("(")[0]}`;
        if (!components.some((component) => component.id === to))
          errors.push(`${from}: unresolved dependency ${name}`);
        relationships.push({ from, to, optional: kind === "optionalDependencies" });
      }
    }
  }
  for (const [path, entry] of Object.entries(sources.frontend.packages).sort()) {
    if (!path) continue;
    const name = entry.name ?? path.split("node_modules/").at(-1);
    checkLicense(name, entry.license);
    components.push({
      id: `npm:${path}`,
      name,
      version: entry.version,
      integrity: entry.integrity,
      license: entry.license ?? null,
      scope: "frontend-lock",
      optional: Boolean(entry.optional),
    });
    for (const kind of ["dependencies", "optionalDependencies"]) {
      for (const [dependency, range] of Object.entries(entry[kind] ?? {}).sort()) {
        // Node resolution: package-local node_modules, then each ancestor node_modules.
        let parent = path;
        let target;
        while (true) {
          const candidate = `${parent ? `${parent}/` : ""}node_modules/${dependency}`;
          if (sources.frontend.packages[candidate]) {
            target = candidate;
            break;
          }
          if (!parent) break;
          parent = parent.includes("/node_modules/")
            ? parent.slice(0, parent.lastIndexOf("/node_modules/"))
            : "";
        }
        if (!target) errors.push(`${path}: unresolved ${dependency}`);
        else
          relationships.push({
            from: `npm:${path}`,
            to: `npm:${target}`,
            range,
            optional: kind === "optionalDependencies",
          });
      }
    }
  }
  const report = {
    bomVersion: "team6-dependency-bom.v1",
    format: "Repository-native lockfile bill of materials; not SPDX/CycloneDX",
    inputs: [
      "package.json",
      "pnpm-lock.yaml",
      "frontend/package.json",
      "frontend/package-lock.json",
      "scripts/policy/licenses.json",
      "scripts/policy/registry-license-metadata.json",
    ].map((path) => fileEvidence(root, path)),
    components,
    relationships,
    errors,
    limitations: [
      "License metadata/drift check, not legal or distribution approval.",
      "Full Node lockfiles including platform-optional packages; does not include OS images or Python build tools.",
      "No live CVE scan; production vulnerability/SBOM gates remain M13.",
    ],
  };
  writeFileSync(
    resolve(root, "docs/execution/dependency-bom.json"),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  execFileSync(
    "corepack",
    ["pnpm", "exec", "biome", "format", "--write", "docs/execution/dependency-bom.json"],
    { cwd: root, stdio: "pipe" },
  );
  if (errors.length) {
    for (const error of errors) console.error(error);
    process.exitCode = 1;
  } else
    console.log(
      `Dependency/license/BOM gate PASS: ${components.length} locked components, ${relationships.length} relationships`,
    );
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
