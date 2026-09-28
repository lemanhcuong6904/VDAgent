import { execFile } from "node:child_process";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import {
  dependencySources,
  frontendLicenses,
  installedLicenses,
  packageIdentity,
} from "./lib/dependencies.mjs";

// Explicit network refresh only; offline gates never update policy or fetch metadata.
const root = fileURLToPath(new URL("../", import.meta.url));
const { backend, frontend } = dependencySources(root);
const known = new Map([...frontendLicenses(frontend), ...installedLicenses(root)]);
const missing = Object.keys(backend.packages)
  .filter((key) => !known.get(key))
  .sort();
const exec = promisify(execFile);
const records = [];
for (let offset = 0; offset < missing.length; offset += 6) {
  const batch = await Promise.all(
    missing.slice(offset, offset + 6).map(async (key) => {
      const identity = packageIdentity(key);
      if (
        !/^(@[a-z0-9-]+\/)?[a-z0-9-]+$/.test(identity.name) ||
        !/^\d+\.\d+\.\d+$/.test(identity.version)
      )
        throw new Error("Unsupported package identity");
      const { stdout } = await exec(
        "npm",
        [
          "view",
          key,
          "name",
          "version",
          "license",
          "dist.integrity",
          "--json",
          "--registry=https://registry.npmjs.org",
        ],
        {
          cwd: root,
          encoding: "utf8",
          timeout: 30_000,
          maxBuffer: 1024 * 1024,
        },
      );
      const parsed = JSON.parse(stdout);
      const metadata = Array.isArray(parsed) && parsed.length === 1 ? parsed[0] : parsed;
      if (
        metadata.name !== identity.name ||
        metadata.version !== identity.version ||
        metadata["dist.integrity"] !== backend.packages[key].resolution.integrity ||
        typeof metadata.license !== "string"
      )
        throw new Error(`${key}: registry metadata does not match locked artifact`);
      return {
        ...identity,
        license: metadata.license,
        integrity: metadata["dist.integrity"],
        source: `https://registry.npmjs.org/${identity.name}/${identity.version}`,
      };
    }),
  );
  records.push(...batch);
  console.log(`Verified public package metadata ${records.length}/${missing.length}`);
}
writeFileSync(
  new URL("./policy/registry-license-metadata.json", import.meta.url),
  `${JSON.stringify({ version: "license-metadata.v1", records }, null, 2)}\n`,
);
