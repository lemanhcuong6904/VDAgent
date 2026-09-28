import type { Pool } from "pg";
import type {
  WarehouseAdapter,
  WarehouseColumn,
  WarehouseTable,
} from "../../warehouse-contract.js";

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_$]{0,127}$/;

/** PostgreSQL-compatible warehouse adapter using parameterized values and bounded results. */
export class PostgresWarehouseAdapter implements WarehouseAdapter {
  readonly id: string;
  readonly name: string;
  readonly capabilities = ["catalog", "query", "sample", "profile"] as const;
  private readonly allowedRelations?: ReadonlySet<string>;

  constructor(
    private readonly pool: Pool,
    id = "postgres",
    name = "PostgreSQL warehouse",
    options: { allowedRelations?: readonly string[] } = {},
  ) {
    assertIdentifier(id);
    this.id = id;
    this.name = name;
    if (options.allowedRelations !== undefined) {
      if (options.allowedRelations.length === 0) {
        throw new Error("PostgreSQL warehouse allowlist must contain at least one relation");
      }
      this.allowedRelations = new Set(options.allowedRelations.map(normalizeRelation));
    }
  }

  async listSchemas(signal: AbortSignal): Promise<string[]> {
    signal.throwIfAborted();
    const result = await this.pool.query<{ schema_name: string }>(
      `SELECT schema_name FROM information_schema.schemata
       WHERE schema_name NOT IN ('pg_catalog', 'information_schema') ORDER BY schema_name`,
    );
    const schemas = new Set(
      [...(this.allowedRelations ?? [])].map((relation) => relation.split(".")[0]),
    );
    return result.rows
      .map(({ schema_name }) => schema_name)
      .filter((schema) => !this.allowedRelations || schemas.has(schema));
  }

  async listTables(signal: AbortSignal): Promise<Array<{ name: string; rowCount: number }>> {
    signal.throwIfAborted();
    const result = await this.pool.query<{ table_schema: string; table_name: string }>(
      `SELECT table_schema, table_name FROM information_schema.tables
       WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')
       ORDER BY table_schema, table_name`,
    );
    return result.rows
      .filter(({ table_schema, table_name }) => this.isAllowed(table_schema, table_name))
      .map(({ table_schema, table_name }) => ({
        name: table_schema === "public" ? table_name : `${table_schema}.${table_name}`,
        rowCount: 0,
      }));
  }

  async describeTable(name: string, signal: AbortSignal): Promise<WarehouseTable> {
    const { schema, relation } = splitRelation(name);
    this.assertAllowed(schema, relation);
    signal.throwIfAborted();
    const columns = await this.columns(schema, relation);
    const sample = await this.query({ table: name, limit: 20 }, signal);
    return { name, columns, rows: sample.rows };
  }

  async describeRelation(
    schema: string,
    relation: string,
    signal: AbortSignal,
  ): Promise<WarehouseTable> {
    return this.describeTable(`${schema}.${relation}`, signal);
  }

  async profile(table: string, signal: AbortSignal): Promise<Record<string, unknown>> {
    const { schema, relation } = splitRelation(table);
    this.assertAllowed(schema, relation);
    signal.throwIfAborted();
    const result = await this.pool.query<{ count: string }>(
      `SELECT count(*)::text AS count FROM ${quote(schema)}.${quote(relation)}`,
    );
    return { table, row_count: Number(result.rows[0]?.count ?? 0) };
  }

  async query(
    input: { table: string; columns?: string[]; limit: number },
    signal: AbortSignal,
  ): Promise<{
    columns: WarehouseColumn[];
    rows: Record<string, string | number | boolean | null>[];
  }> {
    const { schema, relation } = splitRelation(input.table);
    this.assertAllowed(schema, relation);
    const columns = await this.columns(schema, relation);
    const selected = input.columns?.length
      ? columns.filter(({ name }) => input.columns?.includes(name))
      : columns;
    if (!selected.length || selected.length !== (input.columns?.length ?? selected.length)) {
      throw new Error("Unknown or empty PostgreSQL warehouse column selection");
    }
    const limit = Math.min(1000, Math.max(1, Math.floor(input.limit)));
    signal.throwIfAborted();
    const result = await this.pool.query(
      `SELECT ${selected.map(({ name }) => quote(name)).join(", ")}
       FROM ${quote(schema)}.${quote(relation)} LIMIT $1`,
      [limit],
    );
    return {
      columns: selected,
      rows: result.rows.map((row) =>
        Object.fromEntries(selected.map(({ name }) => [name, scalar(row[name])])),
      ),
    };
  }

  private async columns(schema: string, table: string): Promise<WarehouseColumn[]> {
    const result = await this.pool.query<{ column_name: string; data_type: string }>(
      `SELECT column_name, data_type FROM information_schema.columns
       WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position`,
      [schema, table],
    );
    if (!result.rows.length)
      throw new Error(`Unknown PostgreSQL warehouse table '${schema}.${table}'`);
    return result.rows.map(({ column_name, data_type }) => ({
      name: column_name,
      type: data_type,
    }));
  }

  private isAllowed(schema: string, relation: string): boolean {
    return !this.allowedRelations || this.allowedRelations.has(`${schema}.${relation}`);
  }

  private assertAllowed(schema: string, relation: string): void {
    if (!this.isAllowed(schema, relation)) {
      throw new Error(`PostgreSQL warehouse relation '${schema}.${relation}' is not allowlisted`);
    }
  }
}

function splitRelation(value: string): { schema: string; relation: string } {
  const parts = value.split(".");
  if (parts.length === 1) return { schema: "public", relation: assertIdentifier(parts[0]) };
  if (parts.length === 2)
    return { schema: assertIdentifier(parts[0]), relation: assertIdentifier(parts[1]) };
  throw new Error("Warehouse relation must be table or schema.table");
}

function assertIdentifier(value: string): string {
  if (!IDENTIFIER.test(value)) throw new Error(`Invalid warehouse identifier '${value}'`);
  return value;
}

function normalizeRelation(value: string): string {
  const { schema, relation } = splitRelation(value);
  return `${schema}.${relation}`;
}

function quote(value: string): string {
  return `"${assertIdentifier(value)}"`;
}

function scalar(value: unknown): string | number | boolean | null {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return value;
  if (value instanceof Date) return value.toISOString();
  return JSON.stringify(value);
}
