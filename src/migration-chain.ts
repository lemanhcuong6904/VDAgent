import { readFileSync } from "node:fs";

/** Alembic-style migration link: order comes from `downRevision`, never from file names. */
export interface MigrationEntry {
  revision: string;
  downRevision: string | null;
  file: string;
}

/** Order a revision chain from its single root to its single head; reject branches and gaps. */
export function orderMigrations(entries: readonly MigrationEntry[]): MigrationEntry[] {
  const byRevision = new Map<string, MigrationEntry>();
  const children = new Map<string | null, MigrationEntry[]>();
  for (const entry of entries) {
    if (!/^[A-Za-z0-9_]{1,128}$/.test(entry.revision))
      throw new Error(`Invalid migration revision: ${entry.revision}`);
    if (byRevision.has(entry.revision))
      throw new Error(`Duplicate migration revision: ${entry.revision}`);
    byRevision.set(entry.revision, entry);
    children.set(entry.downRevision, [...(children.get(entry.downRevision) ?? []), entry]);
  }
  for (const entry of entries)
    if (entry.downRevision !== null && !byRevision.has(entry.downRevision))
      throw new Error(`Migration ${entry.revision} points to unknown ${entry.downRevision}`);
  for (const [parent, list] of children)
    if (list.length > 1)
      throw new Error(
        `Migration branch at ${parent ?? "root"}: ${list.map((e) => e.revision).join(", ")}; merge into one head`,
      );
  const ordered: MigrationEntry[] = [];
  let next = children.get(null)?.[0];
  while (next) {
    ordered.push(next);
    next = children.get(next.revision)?.[0];
  }
  if (ordered.length !== entries.length)
    throw new Error("Migration chain has a cycle or unreachable revision");
  return ordered;
}

/** Load the chain from versions.json, the single source of truth for revisions. */
export function loadMigrationChain(
  registry = new URL("../versions.json", import.meta.url),
): MigrationEntry[] {
  const parsed = JSON.parse(readFileSync(registry, "utf8")) as { migrations?: MigrationEntry[] };
  if (!Array.isArray(parsed.migrations)) throw new Error("versions.json has no migrations list");
  return orderMigrations(parsed.migrations);
}
