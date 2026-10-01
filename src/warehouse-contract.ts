export interface WarehouseColumn {
  name: string;
  type: string;
}

export interface WarehouseTable {
  name: string;
  columns: WarehouseColumn[];
  rows: Record<string, string | number | boolean | null>[];
}

export interface WarehouseQueryInput {
  table: string;
  columns?: string[];
  limit: number;
}

export interface WarehouseQueryResult {
  columns: WarehouseColumn[];
  rows: Record<string, string | number | boolean | null>[];
}

export interface WarehouseAdapter {
  id: string;
  name: string;
  capabilities?: readonly string[];
  listTables(signal: AbortSignal): Promise<Array<{ name: string; rowCount: number }>>;
  describeTable(name: string, signal: AbortSignal): Promise<WarehouseTable>;
  query(input: WarehouseQueryInput, signal: AbortSignal): Promise<WarehouseQueryResult>;
  listSchemas?(signal: AbortSignal): Promise<string[]>;
  describeRelation?(schema: string, relation: string, signal: AbortSignal): Promise<WarehouseTable>;
  profile?(table: string, signal: AbortSignal): Promise<Record<string, unknown>>;
}

export interface WarehouseSource {
  id: string;
  name: string;
  capabilities: string[];
}

export function validateWarehouseAdapter(adapter: WarehouseAdapter): void {
  if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(adapter.id)) {
    throw new Error(`Invalid warehouse id '${adapter.id}'`);
  }
  if (!adapter.name.trim()) throw new Error(`Warehouse '${adapter.id}' must have a name`);
  const capabilities = adapter.capabilities ?? [];
  if (new Set(capabilities).size !== capabilities.length) {
    throw new Error(`Warehouse '${adapter.id}' declares duplicate capabilities`);
  }
  for (const capability of capabilities) {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(capability)) {
      throw new Error(`Invalid capability '${capability}' for warehouse '${adapter.id}'`);
    }
  }
}
