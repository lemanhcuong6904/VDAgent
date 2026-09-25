import { createAnalyticsAgent } from "../analytics.js";

export const agentPlugin = createAnalyticsAgent({
  id: "report",
  name: "Report",
  description: "Writes and saves reports from comparison, insight, and visualization findings.",
  tools: ["warehouse.describe_dataset", "warehouse.get_dataset_rows", "warehouse.save_report"],
  system:
    "You are the Report specialist. Write a concise report from the supplied Compare, Insight, " +
    "and Visualize outputs. Include the exact persisted chart ID supplied by Visualize and the " +
    "dataset ID. Do not create charts, add unsupported causes, invent values or artifact IDs, " +
    "or paste bulk rows. Save the report only when explicitly requested.",
});
