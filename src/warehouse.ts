import { Type } from "typebox";
import type { McpPoolTool } from "./tool-pool.js";
import type { PostgresWarehouseArtifacts } from "./warehouse-artifacts.js";

export interface WarehouseColumn {
  name: string;
  type: string;
}

export interface WarehouseTable {
  name: string;
  columns: WarehouseColumn[];
  rows: Record<string, string | number | boolean | null>[];
}

export interface WarehouseProvider {
  id: string;
  name: string;
  listTables(signal: AbortSignal): Promise<Array<{ name: string; rowCount: number }>>;
  describeTable(name: string, signal: AbortSignal): Promise<WarehouseTable>;
  query(
    input: { table: string; columns?: string[]; limit: number },
    signal: AbortSignal,
  ): Promise<{
    columns: WarehouseColumn[];
    rows: Record<string, string | number | boolean | null>[];
  }>;
}

export class WarehouseRegistry {
  private readonly providers = new Map<string, WarehouseProvider>();

  register(provider: WarehouseProvider): void {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(provider.id)) {
      throw new Error(`Invalid warehouse id '${provider.id}'`);
    }
    if (this.providers.has(provider.id))
      throw new Error(`Warehouse '${provider.id}' is already registered`);
    this.providers.set(provider.id, provider);
  }

  list(): Array<{ id: string; name: string }> {
    return [...this.providers.values()].map(({ id, name }) => ({ id, name }));
  }

  get(id: string): WarehouseProvider {
    const provider = this.providers.get(id);
    if (!provider) throw new Error(`Unknown warehouse '${id}'`);
    return provider;
  }

  default(): WarehouseProvider {
    const provider = this.providers.values().next().value as WarehouseProvider | undefined;
    if (!provider) throw new Error("No warehouse providers are registered");
    return provider;
  }
}

export function createWarehouseTools(
  registry: WarehouseRegistry,
  artifacts?: PostgresWarehouseArtifacts,
): McpPoolTool[] {
  const warehouseId = Type.Optional(Type.String({ minLength: 1, maxLength: 128 }));
  return [
    {
      name: "warehouse.list_sources",
      description: "List registered data warehouse providers and their IDs.",
      schema: Type.Object({}),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute() {
        return { warehouses: registry.list() };
      },
    },
    {
      name: "warehouse.list_tables",
      description: "List tables in a registered data warehouse.",
      schema: Type.Object({ warehouseId }),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute(input, scope) {
        const value = input as { warehouseId?: string };
        const provider = value.warehouseId ? registry.get(value.warehouseId) : registry.default();
        return { warehouseId: provider.id, tables: await provider.listTables(scope.signal) };
      },
    },
    {
      name: "warehouse.describe_table",
      description:
        "Describe a table and return a small synthetic sample when using the mock provider.",
      schema: Type.Object({ warehouseId, table: Type.String({ minLength: 1, maxLength: 128 }) }),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute(input, scope) {
        const value = input as { warehouseId?: string; table: string };
        const provider = value.warehouseId ? registry.get(value.warehouseId) : registry.default();
        return {
          warehouseId: provider.id,
          table: await provider.describeTable(value.table, scope.signal),
        };
      },
    },
    {
      name: "warehouse.run_query",
      description: "Read rows from a warehouse table and select columns, with a bounded row limit.",
      schema: Type.Object({
        warehouseId,
        table: Type.String({ minLength: 1, maxLength: 128 }),
        columns: Type.Optional(
          Type.Array(Type.String({ minLength: 1, maxLength: 128 }), { maxItems: 32 }),
        ),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 })),
      }),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute(input, scope) {
        const value = input as {
          warehouseId?: string;
          table: string;
          columns?: string[];
          limit?: number;
        };
        const provider = value.warehouseId ? registry.get(value.warehouseId) : registry.default();
        const result = await provider.query(
          { table: value.table, columns: value.columns, limit: value.limit ?? 100 },
          scope.signal,
        );
        if (!artifacts) return { warehouseId: provider.id, ...result };
        const saved = await artifacts.saveDataset(
          {
            name: value.table,
            sourceSql: `SELECT ${result.columns.map(({ name }) => `"${name}"`).join(", ")} FROM "${value.table}" LIMIT ${value.limit ?? 100}`,
            columns: result.columns,
            rows: result.rows,
          },
          scope,
        );
        return {
          warehouseId: provider.id,
          dataset_id: saved.id,
          name: value.table,
          columns: result.columns,
          row_count: saved.row_count,
          truncated: false,
          preview: result.rows.slice(0, 20),
        };
      },
    },
    {
      name: "warehouse.describe_dataset",
      description: "Describe a dataset created by a warehouse query.",
      schema: Type.Object({ datasetId: Type.String({ minLength: 1, maxLength: 128 }) }),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute(input, scope) {
        const store = requireArtifacts(artifacts);
        const dataset = await store.getDataset((input as { datasetId: string }).datasetId, scope);
        if (!dataset) throw new Error("Dataset not found");
        return {
          id: dataset.id,
          name: dataset.name,
          columns: dataset.columns,
          row_count: dataset.rows.length,
        };
      },
    },
    {
      name: "warehouse.get_dataset_rows",
      description: "Read a page from a dataset created by a warehouse query.",
      schema: Type.Object({
        datasetId: Type.String({ minLength: 1, maxLength: 128 }),
        offset: Type.Optional(Type.Integer({ minimum: 0 })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
      }),
      mutates: false,
      agents: ["*"],
      authorize: () => true,
      async execute(input, scope) {
        const value = input as { datasetId: string; offset?: number; limit?: number };
        const dataset = await requireArtifacts(artifacts).getDataset(value.datasetId, scope);
        if (!dataset) throw new Error("Dataset not found");
        const offset = value.offset ?? 0;
        return {
          id: dataset.id,
          columns: dataset.columns,
          row_count: dataset.rows.length,
          rows: dataset.rows.slice(offset, offset + (value.limit ?? 50)),
        };
      },
    },
    {
      name: "warehouse.create_chart",
      description: "Create a Vega-Lite chart from a dataset.",
      schema: Type.Object({
        datasetId: Type.String({ minLength: 1, maxLength: 128 }),
        kind: Type.Union([Type.Literal("bar"), Type.Literal("line")]),
        x: Type.String({ minLength: 1, maxLength: 128 }),
        y: Type.String({ minLength: 1, maxLength: 128 }),
        title: Type.String({ minLength: 1, maxLength: 200 }),
      }),
      mutates: true,
      agents: ["visualize"],
      authorize: () => true,
      async execute(input, scope) {
        const value = input as {
          datasetId: string;
          kind: "bar" | "line";
          x: string;
          y: string;
          title: string;
        };
        const store = requireArtifacts(artifacts);
        const dataset = await store.getDataset(value.datasetId, scope);
        if (
          !dataset?.columns.some(({ name }) => name === value.x) ||
          !dataset.columns.some(({ name }) => name === value.y)
        ) {
          throw new Error("Chart fields must exist in the dataset");
        }
        const spec = {
          $schema: "https://vega.github.io/schema/vega-lite/v5.json",
          title: value.title,
          data: { values: dataset.rows },
          mark: value.kind,
          encoding: {
            x: {
              field: value.x,
              type: /date|time|month/i.test(
                dataset.columns.find(({ name }) => name === value.x)?.type ?? "",
              )
                ? "temporal"
                : "nominal",
            },
            y: { field: value.y, type: "quantitative" },
          },
        };
        return store.saveChart({ datasetId: value.datasetId, title: value.title, spec }, scope);
      },
    },
    {
      name: "warehouse.save_report",
      description:
        "Save a Markdown report; artifact IDs may be embedded as {{dataset:id}} or {{chart:id}}.",
      schema: Type.Object({
        title: Type.String({ minLength: 1, maxLength: 200 }),
        markdown: Type.String({ minLength: 1, maxLength: 20_000 }),
      }),
      mutates: true,
      agents: ["*"],
      authorize: () => true,
      execute(input, scope) {
        const value = input as { title: string; markdown: string };
        const markdown =
          scope.agentId === "report" ? removeUnsupportedCauses(value.markdown) : value.markdown;
        return requireArtifacts(artifacts).saveReport({ ...value, markdown }, scope);
      },
    },
  ];
}

function removeUnsupportedCauses(markdown: string): string {
  const lines = markdown
    .split("\n")
    .filter(
      (line) =>
        !/\b(?:likely|may|might|could|possibly|potential(?:ly)?|indicat\w*|suggest\w*|imply\w*)\b/i.test(
          line,
        ) && !/\b(?:due to|because of|caused by|driven by|results? from)\b/i.test(line),
    );
  return lines
    .filter((line, index) => {
      if (!/^#{1,6}\s/.test(line)) return true;
      let next = index + 1;
      while (next < lines.length && !lines[next]?.trim()) next += 1;
      return next < lines.length && !/^#{1,6}\s/.test(lines[next] ?? "");
    })
    .join("\n");
}

function requireArtifacts(
  artifacts: PostgresWarehouseArtifacts | undefined,
): PostgresWarehouseArtifacts {
  if (!artifacts) throw new Error("Warehouse artifact persistence is not configured");
  return artifacts;
}
