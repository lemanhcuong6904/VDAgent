// Central version manager (alembic-style). versions.json is the only source of truth for contract
// versions and migration order; file names and folders carry no version meaning.
//   pnpm versions list
//   pnpm versions check
//   pnpm versions bump <contract> "<reason>"      # breaking change: next major $id
//   pnpm versions new-migration <slug>             # appends a revision linked to the head
import { randomBytes } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { type MigrationEntry, orderMigrations } from "../src/migration-chain.js";

type Contract = {
  schema: string;
  id: string;
  version: number;
  generated: string | null;
  history: Array<{ version: number; note: string }>;
};
type Registry = {
  registryVersion: 1;
  description: string;
  contracts: Record<string, Contract>;
  migrations: MigrationEntry[];
};

export function checkRegistry(root: string, registry: Registry): string[] {
  const errors: string[] = [];
  const seen = new Set<string>();
  for (const [name, contract] of Object.entries(registry.contracts)) {
    if (contract.id !== `urn:team6:schema:${name}:v${contract.version}`)
      errors.push(`${name}: id ${contract.id} does not match version ${contract.version}`);
    if (contract.history.at(-1)?.version !== contract.version)
      errors.push(`${name}: history does not end at current version`);
    const path = resolve(root, contract.schema);
    if (!existsSync(path)) {
      errors.push(`${name}: missing ${contract.schema}`);
      continue;
    }
    seen.add(contract.schema);
    const schema = JSON.parse(readFileSync(path, "utf8")) as { $id?: string };
    if (schema.$id !== contract.id)
      errors.push(`${name}: ${contract.schema} has $id ${schema.$id}`);
    if (contract.generated && !existsSync(resolve(root, contract.generated)))
      errors.push(`${name}: missing generated ${contract.generated}`);
  }
  for (const file of readdirSync(resolve(root, "schemas")).filter((n) => n.endsWith(".json")))
    if (!seen.has(`schemas/${file}`)) errors.push(`schemas/${file} is not registered`);
  try {
    orderMigrations(registry.migrations);
  } catch (error) {
    errors.push((error as Error).message);
  }
  const files = new Set(registry.migrations.map((entry) => entry.file));
  for (const entry of registry.migrations)
    if (!existsSync(resolve(root, entry.file))) errors.push(`missing ${entry.file}`);
  for (const file of readdirSync(resolve(root, "db/migrations")).filter((n) => n.endsWith(".sql")))
    if (!files.has(`db/migrations/${file}`)) errors.push(`db/migrations/${file} is not registered`);
  return errors;
}

export function bumpContract(registry: Registry, name: string, note: string): Contract {
  const contract = registry.contracts[name];
  if (!contract) throw new Error(`Unknown contract ${name}`);
  if (!note.trim()) throw new Error("A bump needs a reason");
  contract.version += 1;
  contract.id = `urn:team6:schema:${name}:v${contract.version}`;
  contract.history.push({ version: contract.version, note: note.trim() });
  return contract;
}

export function appendMigration(registry: Registry, slug: string): MigrationEntry {
  if (!/^[a-z][a-z0-9_]{0,60}$/.test(slug)) throw new Error("Slug must be snake_case");
  const head = orderMigrations(registry.migrations).at(-1)?.revision ?? null;
  const revision = `${randomBytes(6).toString("hex")}_${slug}`;
  const entry = { revision, downRevision: head, file: `db/migrations/${revision}.sql` };
  registry.migrations.push(entry);
  return entry;
}

function main() {
  const root = fileURLToPath(new URL("../", import.meta.url));
  const path = resolve(root, "versions.json");
  const registry = JSON.parse(readFileSync(path, "utf8")) as Registry;
  const [command = "list", ...args] = process.argv.slice(2);
  const save = () => writeFileSync(path, `${JSON.stringify(registry, null, 2)}\n`);
  if (command === "list") {
    for (const [name, c] of Object.entries(registry.contracts))
      console.log(`contract  ${name.padEnd(20)} v${c.version}  ${c.schema}`);
    const chain = orderMigrations(registry.migrations);
    for (const entry of chain)
      console.log(`migration ${entry.revision} <- ${entry.downRevision ?? "root"}`);
    console.log(`head: ${chain.at(-1)?.revision ?? "none"}`);
  } else if (command === "check") {
    const errors = checkRegistry(root, registry);
    for (const error of errors) console.error(error);
    if (errors.length) process.exitCode = 1;
    else
      console.log(
        `versions.json PASS: ${Object.keys(registry.contracts).length} contracts, ${registry.migrations.length} migrations, single head`,
      );
  } else if (command === "bump") {
    const contract = bumpContract(registry, args[0] ?? "", args[1] ?? "");
    const schemaPath = resolve(root, contract.schema);
    const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as Record<string, unknown>;
    schema.$id = contract.id;
    writeFileSync(schemaPath, `${JSON.stringify(schema, null, 2)}\n`);
    save();
    console.log(
      `${args[0]} -> v${contract.version}; run pnpm contracts:generate and update consumers`,
    );
  } else if (command === "new-migration") {
    const entry = appendMigration(registry, args[0] ?? "");
    writeFileSync(
      resolve(root, entry.file),
      `-- revision: ${entry.revision}\n-- down_revision: ${entry.downRevision}\n`,
      {
        flag: "wx",
      },
    );
    save();
    console.log(`created ${entry.file} (down_revision ${entry.downRevision})`);
  } else {
    console.error(
      "Usage: pnpm versions [list|check|bump <contract> <reason>|new-migration <slug>]",
    );
    process.exitCode = 1;
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) main();
