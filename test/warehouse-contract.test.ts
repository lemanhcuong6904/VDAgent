import { describe, expect, it } from "vitest";
import { WarehouseRegistry } from "../src/warehouse.js";

describe("warehouse adapter contract", () => {
  it("catalogs capabilities for more than one provider", () => {
    const registry = new WarehouseRegistry();
    const adapter = {
      id: "warehouse-a",
      name: "Warehouse A",
      capabilities: ["catalog", "query"],
      async listTables() {
        return [];
      },
      async describeTable() {
        return { name: "orders", columns: [], rows: [] };
      },
      async query() {
        return { columns: [], rows: [] };
      },
    };
    registry.register(adapter);
    registry.register({ ...adapter, id: "warehouse-b", name: "Warehouse B" });

    expect(registry.list()).toEqual([
      { id: "warehouse-a", name: "Warehouse A", capabilities: ["catalog", "query"] },
      { id: "warehouse-b", name: "Warehouse B", capabilities: ["catalog", "query"] },
    ]);
  });

  it("rejects invalid adapter capability names", () => {
    const registry = new WarehouseRegistry();
    expect(() =>
      registry.register({
        id: "warehouse-a",
        name: "Warehouse A",
        capabilities: ["bad capability"],
        async listTables() {
          return [];
        },
        async describeTable() {
          return { name: "orders", columns: [], rows: [] };
        },
        async query() {
          return { columns: [], rows: [] };
        },
      }),
    ).toThrow("Invalid capability");
  });
});
