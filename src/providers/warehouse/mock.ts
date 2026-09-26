import type { WarehouseProvider, WarehouseTable } from "../../warehouse.js";

const tables: WarehouseTable[] = [
  {
    name: "monthly_sales",
    columns: [
      { name: "month", type: "date" },
      { name: "region", type: "text" },
      { name: "revenue", type: "number" },
    ],
    rows: [
      { month: "2025-01", region: "North", revenue: 120 },
      { month: "2025-02", region: "North", revenue: 145 },
      { month: "2025-01", region: "South", revenue: 98 },
      { month: "2025-02", region: "South", revenue: 91 },
    ],
  },
  {
    name: "customers",
    columns: [
      { name: "segment", type: "text" },
      { name: "customer_count", type: "number" },
    ],
    rows: [
      { segment: "SMB", customer_count: 84 },
      { segment: "Enterprise", customer_count: 16 },
    ],
  },
];

function tableOrThrow(name: string): WarehouseTable {
  const table = tables.find((item) => item.name === name);
  if (!table) throw new Error(`Unknown mock table '${name}'`);
  return table;
}

export const warehouse: WarehouseProvider = {
  id: "sample-warehouse",
  name: "Synthetic sales warehouse",
  capabilities: ["catalog", "query", "sample", "persist-dataset"],
  async listTables(signal) {
    signal.throwIfAborted();
    return tables.map(({ name, rows }) => ({ name, rowCount: rows.length }));
  },
  async describeTable(name, signal) {
    signal.throwIfAborted();
    return tableOrThrow(name);
  },
  async query(input, signal) {
    signal.throwIfAborted();
    const table = tableOrThrow(input.table);
    const columns = input.columns?.length
      ? table.columns.filter(({ name }) => input.columns?.includes(name))
      : table.columns;
    if (input.columns?.some((name) => !table.columns.some((column) => column.name === name))) {
      throw new Error("Unknown column in mock warehouse query");
    }
    const rows = table.rows
      .slice(0, input.limit)
      .map((row) => Object.fromEntries(columns.map(({ name }) => [name, row[name]])));
    return { columns, rows };
  },
};
