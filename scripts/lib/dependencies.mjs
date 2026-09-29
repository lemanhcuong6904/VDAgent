import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parse } from "yaml";

export const readJson = (root, path) => JSON.parse(readFileSync(resolve(root, path), "utf8"));
export const packageIdentity = (key) => {
  const clean = key.split("(")[0];
  const split = clean.lastIndexOf("@");
  return { name: clean.slice(0, split), version: clean.slice(split + 1) };
};
export function dependencySources(root) {
  return {
    backend: parse(readFileSync(resolve(root, "pnpm-lock.yaml"), "utf8")),
    frontend: readJson(root, "frontend/package-lock.json"),
    manifests: [readJson(root, "package.json"), readJson(root, "frontend/package.json")],
  };
}
export function installedLicenses(root) {
  const report = JSON.parse(
    execFileSync("corepack", ["pnpm", "licenses", "list", "--json"], {
      cwd: root,
      encoding: "utf8",
      timeout: 60_000,
      maxBuffer: 8 * 1024 * 1024,
      stdio: ["ignore", "pipe", "pipe"],
    }),
  );
  const licenses = new Map();
  for (const [license, packages] of Object.entries(report)) {
    for (const entry of packages)
      for (const version of entry.versions) licenses.set(`${entry.name}@${version}`, license);
  }
  return licenses;
}
export function frontendLicenses(frontend) {
  return new Map(
    Object.entries(frontend.packages)
      .filter(([path]) => path)
      .map(([path, entry]) => [
        `${entry.name ?? path.split("node_modules/").at(-1)}@${entry.version}`,
        entry.license,
      ]),
  );
}

export function dependencyErrors(sources) {
  const errors = [];
  const { backend, frontend, manifests } = sources;
  if (Number(backend.lockfileVersion) !== 9) errors.push("Unsupported pnpm lock version");
  if (frontend.lockfileVersion !== 3) errors.push("Unsupported npm lock version");
  for (let index = 0; index < manifests.length; index++) {
    for (const kind of ["dependencies", "devDependencies", "optionalDependencies"]) {
      const declared = manifests[index][kind] ?? {};
      const locked =
        index === 0
          ? (backend.importers?.["."]?.[kind] ?? {})
          : (frontend.packages?.[""]?.[kind] ?? {});
      if (Object.keys(declared).sort().join() !== Object.keys(locked).sort().join())
        errors.push(`${index}:${kind}: lock importer differs`);
      for (const [name, version] of Object.entries(declared)) {
        if (!/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/.test(version))
          errors.push(`${name}: direct version must be exact`);
        const lockedSpec = index === 0 ? locked[name]?.specifier : locked[name];
        const resolved =
          index === 0
            ? locked[name]?.version?.split("(")[0]
            : frontend.packages[`node_modules/${name}`]?.version;
        if (lockedSpec !== version || resolved !== version)
          errors.push(`${name}: manifest/lock resolution mismatch`);
      }
    }
  }
  for (const [key, entry] of Object.entries(backend.packages)) {
    if (!/^sha512-[A-Za-z0-9+/]+={0,2}$/.test(entry.resolution?.integrity ?? ""))
      errors.push(`${key}: missing SHA-512 lock integrity`);
  }
  for (const [path, entry] of Object.entries(frontend.packages)) {
    if (path && (!/^sha512-[A-Za-z0-9+/]+={0,2}$/.test(entry.integrity ?? "") || !entry.version))
      errors.push(`${path}: missing version/integrity`);
  }
  return errors;
}
