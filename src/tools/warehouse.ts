import type { Pool } from "pg";
import { warehouse } from "../providers/warehouse/mock.js";
import { createWarehouseTools, WarehouseRegistry } from "../warehouse.js";
import { PostgresWarehouseArtifacts } from "../warehouse-artifacts.js";

export const warehouseRegistry = new WarehouseRegistry();
warehouseRegistry.register(warehouse);
export function createTools(services: { database?: Pool }) {
  if (!services.database) throw new Error("Warehouse tools require the API database");
  return createWarehouseTools(warehouseRegistry, new PostgresWarehouseArtifacts(services.database));
}
