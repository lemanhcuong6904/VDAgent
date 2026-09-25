import { createAnalyticsAgent } from "../analytics.js";

export const agentPlugin = createAnalyticsAgent({
  id: "compare",
  name: "Compare",
  description: "Compares periods and segments from supplied warehouse datasets.",
  tools: ["warehouse.describe_dataset", "warehouse.get_dataset_rows"],
  system:
    "You are the Compare specialist. Compare only supplied datasets. Quantify absolute and " +
    "percentage changes when values support them. State the compared periods and dataset IDs. " +
    "Do not invent missing data or paste raw rows.",
});
