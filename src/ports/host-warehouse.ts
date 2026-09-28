/**
 * Production WarehousePort over the pool warehouse tools (src/warehouse.ts). A dataset id is
 * "<sourceId>/<table>". Queries are host-registered table reads (no raw SQL); `parameters` may
 * narrow `columns`. run_query persists a dataset and returns a preview, so `truncated` is true
 * when the stored dataset has more rows than returned here.
 */
import type { AgentContext } from "../agent-contract.js";
import type { AgentManifest, AgentPorts, JsonValue } from "../contracts/index.js";
import {
  type CallOptions,
  failure,
  granted,
  inactive,
  jsonBytes,
  poolScope,
} from "./host-outcome.js";

const LIMITATION = "Query rows are the persisted dataset preview (at most 20 rows).";
const split = (datasetId: string) => {
  const index = datasetId.indexOf("/");
  return index > 0
    ? { warehouseId: datasetId.slice(0, index), table: datasetId.slice(index + 1) }
    : undefined;
};

export function createHostWarehousePort(
  manifest: AgentManifest,
  context: AgentContext,
  correlationId: string,
): AgentPorts["warehouse"] {
  const declared = manifest.requiredPorts.includes("warehouse");
  const gate = (tool: string, options: CallOptions) => {
    if (!declared) return failure("denied", "port_not_declared", correlationId);
    if (!granted(manifest, context, tool))
      return failure("denied", "warehouse_not_granted", correlationId);
    if (inactive(options)) return failure("failed", "inactive_call", correlationId);
    return undefined;
  };
  const call = (tool: string, input: unknown, options: CallOptions) =>
    context.pool.call(tool, input, poolScope(manifest, context, options.signal), manifest.id);
  const ok = <T>(output: T) => ({
    status: "ok" as const,
    output,
    evidence: [],
    limitations: [LIMITATION],
  });

  return {
    async catalog(options) {
      const denied =
        gate("warehouse.list_tables", options) ?? gate("warehouse.list_sources", options);
      if (denied) return denied;
      try {
        const sources = (await call("warehouse.list_sources", {}, options)) as {
          warehouses: Array<{ id: string; name: string }>;
        };
        const output: Array<{ id: string; displayName: string }> = [];
        for (const source of sources.warehouses) {
          const listed = (await call(
            "warehouse.list_tables",
            { warehouseId: source.id },
            options,
          )) as {
            tables: Array<{ name: string }>;
          };
          for (const table of listed.tables) {
            output.push({
              id: `${source.id}/${table.name}`,
              displayName: `${source.name}: ${table.name}`,
            });
          }
        }
        return ok(output);
      } catch {
        return failure("failed", "warehouse_failed", correlationId);
      }
    },
    async describe(input, options) {
      const denied = gate("warehouse.describe_table", options);
      if (denied) return denied;
      const target = split(input.datasetId);
      if (!target || target.warehouseId !== input.sourceId)
        return failure("failed", "unknown_dataset", correlationId);
      try {
        const described = (await call("warehouse.describe_table", target, options)) as {
          table: { columns: Array<{ name: string; type: string }> };
        };
        return ok({ columns: described.table.columns.map(({ name, type }) => ({ name, type })) });
      } catch {
        return failure("failed", "warehouse_failed", correlationId);
      }
    },
    async query(input, options) {
      const denied = gate("warehouse.run_query", options);
      if (denied) return denied;
      const target = split(input.queryId);
      if (!target) return failure("failed", "unknown_query", correlationId);
      const columns = Array.isArray(input.parameters.columns)
        ? input.parameters.columns.filter((value): value is string => typeof value === "string")
        : undefined;
      let result: { preview?: JsonValue[]; rows?: JsonValue[]; row_count?: number };
      try {
        result = (await call(
          "warehouse.run_query",
          {
            ...target,
            ...(columns && { columns }),
            limit: Math.min(1000, Math.max(1, input.maxRows)),
          },
          options,
        )) as typeof result;
      } catch {
        // Persisting the dataset is a write, but a read-only query failure has no user effect.
        return failure("failed", "warehouse_failed", correlationId);
      }
      const available = result.preview ?? result.rows ?? [];
      const rows: JsonValue[] = [];
      for (const row of available.slice(0, input.maxRows)) {
        if (jsonBytes([...rows, row]) > input.maxBytes) break;
        rows.push(row);
      }
      const total = result.row_count ?? available.length;
      return ok({ rows, truncated: rows.length < total });
    },
  };
}
