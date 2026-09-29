import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { appendMigration, bumpContract, checkRegistry } from "../scripts/versions.js";
import { KNOWN_MIGRATIONS } from "../src/database.js";
import { type MigrationEntry, orderMigrations } from "../src/migration-chain.js";

const registry = () => JSON.parse(readFileSync("versions.json", "utf8"));
const link = (revision: string, downRevision: string | null): MigrationEntry => ({
  revision,
  downRevision,
  file: `db/migrations/${revision}.sql`,
});

describe("central version registry", () => {
  it("matches every schema, generated file and migration in the repository", () => {
    expect(checkRegistry(process.cwd(), registry())).toEqual([]);
  });

  it("drives the migration runner order and keeps applied revision ids", () => {
    expect(KNOWN_MIGRATIONS[0]).toBe("001_agent_memory_and_pi_sessions");
    expect(KNOWN_MIGRATIONS).toEqual(orderMigrations(registry().migrations).map((e) => e.revision));
  });

  it("orders by down_revision, not by name or list position", () => {
    const ordered = orderMigrations([link("zz_last", "aa_first"), link("aa_first", null)]);
    expect(ordered.map((e) => e.revision)).toEqual(["aa_first", "zz_last"]);
  });

  it("rejects branches, gaps, cycles and duplicates", () => {
    expect(() => orderMigrations([link("a", null), link("b", "a"), link("c", "a")])).toThrow(
      /branch/,
    );
    expect(() => orderMigrations([link("a", null), link("b", "missing")])).toThrow(/unknown/);
    expect(() => orderMigrations([link("a", "b"), link("b", "a")])).toThrow(/cycle/);
    expect(() => orderMigrations([link("a", null), link("a", null)])).toThrow(/Duplicate/);
  });

  it("appends new migrations to the current head", () => {
    const value = registry();
    const head = orderMigrations(value.migrations).at(-1)?.revision;
    const entry = appendMigration(value, "add_index");
    expect(entry.downRevision).toBe(head);
    expect(orderMigrations(value.migrations).at(-1)).toEqual(entry);
  });

  it("bumps a contract major with a recorded reason", () => {
    const value = registry();
    const bumped = bumpContract(value, "agent-scope", "breaking: rename actor field");
    expect(bumped.id).toBe(`urn:team6:schema:agent-scope:v${bumped.version}`);
    expect(bumped.history.at(-1)?.note).toMatch(/breaking/);
    expect(() => bumpContract(value, "agent-scope", " ")).toThrow();
  });
});
