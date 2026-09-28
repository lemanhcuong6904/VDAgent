import type { Pool } from "pg";
import { warehouse } from "../providers/warehouse/mock.js";
import { PostgresWarehouseAdapter } from "../providers/warehouse/postgres.js";
import { createWarehouseTools, WarehouseRegistry } from "../warehouse.js";
import { PostgresWarehouseArtifacts } from "../warehouse-artifacts.js";

export const warehouseRegistry = new WarehouseRegistry();

export function createTools(services: { database?: Pool; warehouseDatabase?: Pool }) {
  if (!services.database) throw new Error("Warehouse tools require the application database");
  const registry = new WarehouseRegistry();
  if (process.env.NODE_ENV === "production") {
    if (process.env.WAREHOUSE_POSTGRES_ENABLED !== "true" || !services.warehouseDatabase) {
      throw new Error(
        "Production requires WAREHOUSE_POSTGRES_ENABLED=true and a separate WAREHOUSE_DATABASE_URL",
      );
    }
    const allowlist = (process.env.WAREHOUSE_ALLOWED_TABLES ?? "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    if (allowlist.length === 0) {
      throw new Error("Production requires a non-empty WAREHOUSE_ALLOWED_TABLES allowlist");
    }
    registry.register(
      new PostgresWarehouseAdapter(services.warehouseDatabase, "postgres", "PostgreSQL warehouse", {
        allowedRelations: allowlist,
      }),
    );
  } else if (process.env.WAREHOUSE_POSTGRES_ENABLED === "true") {
    const warehouseDatabase = services.warehouseDatabase ?? services.database;
    registry.register(new PostgresWarehouseAdapter(warehouseDatabase, "postgres"));
  } else {
    registry.register(warehouse);
  }
  return createWarehouseTools(registry, new PostgresWarehouseArtifacts(services.database));
}
