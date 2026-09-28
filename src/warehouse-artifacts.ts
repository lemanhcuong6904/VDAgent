import { createHash, randomUUID } from "node:crypto";
import type { Pool } from "pg";
import type { ToolScope } from "./tool-pool.js";
import type { WarehouseColumn } from "./warehouse.js";

export class PostgresWarehouseArtifacts {
  constructor(private readonly database: Pool) {}

  async saveDataset(
    input: {
      name: string;
      sourceSql: string;
      columns: WarehouseColumn[];
      rows: Record<string, unknown>[];
    },
    scope: ToolScope,
  ) {
    const encodedColumns = JSON.stringify(input.columns);
    const encodedRows = JSON.stringify(input.rows);
    if (Buffer.byteLength(encodedColumns) + Buffer.byteLength(encodedRows) > 8_000_000) {
      throw new Error("Warehouse dataset exceeds the persistence byte limit");
    }
    // Query retries must converge on one dataset. Include the authenticated run and
    // exact result in the key so a different query cannot replay the old dataset.
    const id = deterministicDatasetId(scope, input.sourceSql, encodedColumns, encodedRows);
    await this.database.query(
      `INSERT INTO web_datasets (id, user_id, invocation_id, name, columns, rows, source_sql)
       VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
       ON CONFLICT (id) DO NOTHING`,
      [
        id,
        scope.userId,
        scope.runId ?? null,
        input.name,
        encodedColumns,
        encodedRows,
        input.sourceSql,
      ],
    );
    return { id, row_count: input.rows.length };
  }

  async getDataset(id: string, scope: ToolScope) {
    const result = await this.database.query<{
      id: string;
      name: string;
      columns: WarehouseColumn[];
      rows: Record<string, unknown>[];
      source_sql: string;
    }>(
      `SELECT id, name, columns, rows, source_sql FROM web_datasets
       WHERE id = $1 AND user_id = $2`,
      [id, scope.userId],
    );
    return result.rows[0];
  }

  async saveChart(
    input: {
      datasetId: string;
      title: string;
      spec: Record<string, unknown>;
    },
    scope: ToolScope,
  ) {
    const id = artifactId("ch");
    const dataset = await this.getDataset(input.datasetId, scope);
    if (!dataset) throw new Error("Dataset not found");
    await this.database.query(
      `INSERT INTO web_charts (id, user_id, invocation_id, dataset_id, title, spec)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
      [
        id,
        scope.userId,
        scope.runId ?? null,
        input.datasetId,
        input.title,
        JSON.stringify(input.spec),
      ],
    );
    return { id, embed: `{{chart:${id}}}` };
  }

  async saveReport(input: { title: string; markdown: string }, scope: ToolScope) {
    const id = artifactId("rp");
    const charts = scope.taskId
      ? await this.database.query<{ id: string }>(
          `SELECT c.id FROM web_charts c
           JOIN web_invocations i ON i.id = c.invocation_id
           WHERE c.user_id = $1 AND i.task_id = $2 ORDER BY c.created_at`,
          [scope.userId, scope.taskId],
        )
      : scope.runId
        ? await this.database.query<{ id: string }>(
            "SELECT id FROM web_charts WHERE user_id = $1 AND invocation_id = $2",
            [scope.userId, scope.runId],
          )
        : { rows: [] };
    const missingEmbeds = charts.rows
      .map(({ id: chartId }) => `{{chart:${chartId}}}`)
      .filter((embed) => !input.markdown.includes(embed));
    const markdown = missingEmbeds.length
      ? `${input.markdown.trim()}\n\n${missingEmbeds.join("\n\n")}`
      : input.markdown;
    const updated = scope.runId
      ? await this.database.query<{ id: string }>(
          `UPDATE web_reports SET title = $3, markdown = $4
           WHERE user_id = $1 AND invocation_id = $2 RETURNING id`,
          [scope.userId, scope.runId, input.title, markdown],
        )
      : { rows: [] };
    const reportId = updated.rows[0]?.id;
    if (reportId) return { id: reportId, embed: `{{report:${reportId}}}` };
    await this.database.query(
      `INSERT INTO web_reports (id, user_id, invocation_id, title, markdown)
       VALUES ($1, $2, $3, $4, $5)`,
      [id, scope.userId, scope.runId ?? null, input.title, markdown],
    );
    return { id, embed: `{{report:${id}}}` };
  }
}

function deterministicDatasetId(
  scope: ToolScope,
  sourceSql: string,
  columns: string,
  rows: string,
): string {
  const digest = createHash("sha256")
    .update(
      JSON.stringify([scope.userId, scope.spaceId, scope.runId ?? null, sourceSql, columns, rows]),
    )
    .digest("hex")
    .slice(0, 24);
  return `ds_${digest}`;
}

function artifactId(prefix: string): string {
  return `${prefix}_${randomUUID().replaceAll("-", "").slice(0, 12)}`;
}
