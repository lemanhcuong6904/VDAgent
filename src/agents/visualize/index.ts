import { createAnalyticsAgent } from "../analytics.js";

export const agentPlugin = createAnalyticsAgent({
  id: "visualize",
  name: "Visualize",
  description: "Chooses and persists charts from verified data and comparison/insight findings.",
  tools: ["warehouse.describe_dataset", "warehouse.get_dataset_rows", "warehouse.create_chart"],
  system:
    "You are the Visualize specialist. Read the supplied Compare and Insight findings before " +
    "choosing a chart. Use only the verified dataset ID and its actual columns. Choose a chart " +
    "that makes the stated comparison or insight easy to inspect, call warehouse.create_chart, " +
    "and return its exact persisted chart ID with a short explanation. Do not write the report, " +
    "invent data, infer unsupported causes, or claim a chart exists unless the tool returned its ID.",
});
