import type { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { warehouse } from "../src/providers/warehouse/mock.js";
import { McpToolPool } from "../src/tool-pool.js";
import { createWarehouseTools, WarehouseRegistry } from "../src/warehouse.js";
import { PostgresWarehouseArtifacts } from "../src/warehouse-artifacts.js";

const scope = {
  userId: "user-test",
  spaceId: "space-test",
  agentId: "data",
  signal: new AbortController().signal,
};

describe("warehouse provider pool", () => {
  it("registers multiple providers and dispatches bounded queries by warehouse id", async () => {
    const registry = new WarehouseRegistry();
    registry.register(warehouse);
    registry.register({
      ...warehouse,
      id: "second-warehouse",
      name: "Second mock warehouse",
      async listTables(signal) {
        signal.throwIfAborted();
        return [{ name: "alternate", rowCount: 0 }];
      },
    });
    const pool = new McpToolPool();
    for (const tool of createWarehouseTools(registry)) pool.register(tool);

    expect(registry.list().map(({ id }) => id)).toEqual(["sample-warehouse", "second-warehouse"]);
    const sources = await pool.call("warehouse.list_sources", {}, scope, "data");
    expect(sources).toMatchObject({
      warehouses: [
        { id: "sample-warehouse", name: "Synthetic sales warehouse" },
        { id: "second-warehouse", name: "Second mock warehouse" },
      ],
    });
    const result = await pool.call(
      "warehouse.run_query",
      { warehouseId: "sample-warehouse", table: "monthly_sales", columns: ["revenue"], limit: 1 },
      scope,
      "data",
    );
    expect(result).toMatchObject({
      warehouseId: "sample-warehouse",
      columns: [{ name: "revenue", type: "number" }],
      rows: [{ revenue: 120 }],
    });
    await expect(
      pool.call(
        "warehouse.describe_table",
        { warehouseId: "missing", table: "monthly_sales" },
        scope,
        "data",
      ),
    ).rejects.toThrow("Unknown warehouse 'missing'");
  });

  it("rejects duplicate providers and unknown mock tables", async () => {
    const registry = new WarehouseRegistry();
    registry.register(warehouse);
    expect(() => registry.register(warehouse)).toThrow("already registered");
    await expect(warehouse.describeTable("missing", scope.signal)).rejects.toThrow(
      "Unknown mock table 'missing'",
    );
  });

  it("removes unsupported causal claims from reports written by Report", async () => {
    let savedMarkdown = "";
    const database = {
      async query(sql: string, values: unknown[]) {
        if (sql.includes("FROM web_charts")) return { rows: [{ id: "ch_123456abcdef" }] };
        if (sql.includes("UPDATE web_reports")) return { rows: [] };
        savedMarkdown = String(values[4]);
        return { rows: [] };
      },
    } as unknown as Pool;
    const pool = new McpToolPool();
    for (const tool of createWarehouseTools(
      new WarehouseRegistry(),
      new PostgresWarehouseArtifacts(database),
    )) {
      pool.register(tool);
    }

    await pool.call(
      "warehouse.save_report",
      {
        title: "Monthly sales",
        markdown:
          "North increased by 20%.\nNorth likely grew due to marketing.\nOnly two months are covered.",
      },
      { ...scope, agentId: "report", runId: "inv-report" },
      "report",
    );

    expect(savedMarkdown).toContain("North increased by 20%.");
    expect(savedMarkdown).toContain("Only two months are covered.");
    expect(savedMarkdown).toContain("{{chart:ch_123456abcdef}}");
    expect(savedMarkdown).not.toContain("marketing");
  });
});
