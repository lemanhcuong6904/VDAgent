import { Type } from "typebox";
import type { AgentContext, AgentPlugin } from "../agent-contract.js";
import { buildCapabilityPlan, type PlanSpec } from "../planner.js";

const input = Type.Object({ prompt: Type.String({ minLength: 1, maxLength: 4000 }) });

export type AnalyticsAgentConfig = {
  id: string;
  name: string;
  description: string;
  tools: string[];
  system: string;
  capabilities?: string[];
  modelProfile?: string;
};

export function createAnalyticsAgent(config: AnalyticsAgentConfig): AgentPlugin {
  return {
    descriptor: {
      id: config.id,
      version: "1.0.0",
      name: config.name,
      description: config.description,
      apiVersion: "agent-plugin.v1",
      capabilities: config.capabilities ?? [config.id, "analytics", "pi"],
      modelProfile: config.modelProfile,
      acceptsDelegation: config.id !== "orchestrator",
      input,
      output: Type.String(),
      guardrails: [
        "Use only evidence available in the scoped tools and supplied prompt.",
        "Never expose secrets or claim an artifact that was not persisted.",
      ],
      tools: config.tools,
    },
    async run(value, context) {
      const prompt = (value as { prompt: string }).prompt;
      if (config.id === "orchestrator" && (context.depth ?? 0) === 0) {
        if (context.catalog) {
          const plan = buildCapabilityPlan(prompt, context.catalog);
          if (plan) return runPlannedWorkflow(context, prompt, config.system, plan);
        } else if (isAnalyticsRequest(prompt)) {
          return runAnalyticsWorkflow(context, prompt, config.system);
        }
      }
      let verifiedEvidence: unknown;
      if (config.id === "data") {
        try {
          verifiedEvidence = await prepareNamedTable(context, prompt);
        } catch (failure) {
          if (context.signal.aborted) throw failure;
          verifiedEvidence = {
            preflight_error: failure instanceof Error ? failure.message : "Warehouse lookup failed",
          };
        }
      }
      let response: string;
      try {
        response = await context.runtime.prompt({
          agentId: config.id,
          system: `${config.system}\n\nUse at most 4 tool calls for this request.`,
          prompt: verifiedEvidence
            ? `${prompt}\n\nVerified warehouse evidence: ${JSON.stringify(verifiedEvidence)}`
            : prompt,
          tools: context.tools.map(({ name }) => name),
          modelProfile: context.modelProfile ?? config.modelProfile,
          scope: runtimeScope(context),
          pool: context.pool,
        });
      } catch (failure) {
        if (config.id === "report" && !context.signal.aborted) {
          return createFallbackReport(context, prompt);
        }
        if (config.id === "visualize" && !context.signal.aborted) {
          return createFallbackVisualization(context, prompt);
        }
        throw failure;
      }
      if (config.id === "report") return createFallbackReport(context, prompt, response);
      const datasetId = extractDatasetId(verifiedEvidence);
      return datasetId ? `${response}\n\nPersisted dataset: ${datasetId}` : response;
    },
  };
}

async function runPlannedWorkflow(
  context: AgentContext,
  prompt: string,
  system: string,
  plan: PlanSpec,
): Promise<string> {
  const results: string[] = [];
  for (const step of plan.steps) {
    const previous = results.length ? `\n\nPrevious step results:\n${results.join("\n\n")}` : "";
    const result = stringifyResult(
      await delegateToCapability(
        context,
        step.capability,
        `${prompt}\n\nYou are step '${step.id}' in a typed plan. Return only evidence and a concise result.` +
          previous,
      ),
    );
    results.push(`[${step.capability}]\n${result}`);
    if (step.capability === "warehouse.query" && !/\bds_[a-zA-Z0-9]{12}\b/.test(result)) {
      break;
    }
  }
  const answer = await context.runtime.prompt({
    agentId: "orchestrator",
    system:
      `${system}\n\nUse only evidence in the persisted plan results below. Do not invent artifacts or ` +
      "claim a step ran when it returned an error. State missing data/capability plainly.",
    prompt: `${prompt}\n\nPlan: ${JSON.stringify(plan)}\n\nResults:\n${results.join("\n\n")}`,
    tools: [],
    scope: runtimeScope(context),
    pool: context.pool,
  });
  return sanitizeFinalAnswer(answer, results);
}

async function runAnalyticsWorkflow(
  context: AgentContext,
  prompt: string,
  system: string,
): Promise<string> {
  const scope = runtimeScope(context);
  const results: string[] = [];
  const data = await context.pool.call(
    "agents.delegate",
    { agent: "data", message: prompt },
    scope,
    "orchestrator",
  );
  const dataResult = stringifyResult(data);
  results.push(`[data]\n${dataResult}`);
  const datasetId = dataResult.match(/\bds_[a-zA-Z0-9]{12}\b/)?.[0];
  if (!datasetId || dataResult.startsWith("error:")) {
    return context.runtime.prompt({
      agentId: "orchestrator",
      system:
        `${system}\n\nData did not return a persisted dataset ID. Explain the limitation briefly. ` +
        "Do not invent an ID or claim another agent ran.",
      prompt: results.join("\n\n"),
      tools: [],
      scope,
      pool: context.pool,
    });
  }

  const reportRequested = needsReport(prompt);
  let compareResult = "No comparison requested.";
  let insightResult = "No insight requested.";
  let visualizeResult = "No chart requested.";
  if (needsComparison(prompt) || reportRequested) {
    compareResult = stringifyResult(
      await delegateTo(
        context,
        "compare",
        `${clip(prompt, 900)}\n\n[data]\n${clip(dataResult, 650)}\nUse dataset ${datasetId}.`,
      ),
    );
    results.push(`[compare]\n${compareResult}`);
  }
  if (needsInsight(prompt) || reportRequested) {
    insightResult = stringifyResult(
      await delegateTo(
        context,
        "insight",
        `${clip(prompt, 900)}\n\n[data]\n${clip(dataResult, 500)}\n\n[compare]\n${clip(compareResult, 700)}\nUse dataset ${datasetId}.`,
      ),
    );
    results.push(`[insight]\n${insightResult}`);
  }
  if (reportRequested) {
    visualizeResult = stringifyResult(
      await delegateTo(
        context,
        "visualize",
        `${clip(prompt, 700)}\n\n[data]\n${clip(dataResult, 400)}\n\n[compare]\n${clip(compareResult, 700)}\n\n[insight]\n${clip(insightResult, 700)}\nUse dataset ${datasetId}. Choose a chart based on the Compare and Insight outputs, then persist it.`,
      ),
    );
    results.push(`[visualize]\n${visualizeResult}`);
    results.push(
      `[report]\n${stringifyResult(await delegateTo(context, "report", `${clip(prompt, 650)}\n\nVerified dataset: ${datasetId}\n\n[compare]\n${clip(compareResult, 650)}\n\n[insight]\n${clip(insightResult, 650)}\n\n[visualize]\n${clip(visualizeResult, 650)}\nWrite the report from these three specialist outputs. Save it only when requested.`))}`,
    );
  }

  const answer = await context.runtime.prompt({
    agentId: "orchestrator",
    system:
      `${system}\n\nThe backend has completed the required specialist calls. Use only their evidence, ` +
      "cite exact artifact IDs, omit causes not established by evidence, and answer in at most " +
      "120 words unless the user requested a report. If a specialist result starts with `error:`, " +
      "state that the requested work failed; never claim an artifact was saved without its ID. " +
      "Do not call tools or describe internal workflow.",
    prompt: `${prompt}\n\nSpecialist results:\n${results.join("\n\n")}`,
    tools: [],
    scope,
    pool: context.pool,
  });
  return sanitizeFinalAnswer(answer, results);
}

function sanitizeFinalAnswer(answer: string, results: readonly string[]): string {
  const artifactIds = [
    ...new Set(results.join("\n").match(/\b(?:ds|ch|rp)_[a-zA-Z0-9]{12}\b/g) ?? []),
  ];
  const validIds = new Set(artifactIds);
  const safeAnswer = answer
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(
      /(?:sandbox:)?\{\{\s*(?:dataset|chart|report)\s*:\s*((?:ds|ch|rp)_[a-zA-Z0-9]{12})\s*\}\}/gi,
      "$1",
    )
    .replace(
      /\[[^\]]*\]\((?:(?:sandbox|dataset|chart|report):)?((?:ds|ch|rp)_[a-zA-Z0-9]{12})\)/g,
      "$1",
    )
    .split("\n")
    .filter(
      (line) =>
        !/\b(?:likely|might|may|could|possibly|potentially|indicat\w*|suggest\w*|imply\w*)\b|\b(?:due to|because of|result(?:s|ed)? from|caused by|driven by)\b/i.test(
          line,
        ),
    )
    .join("\n")
    .replace(/\b(?:ds|ch|rp)_[a-zA-Z0-9]{12}\b/g, (id) =>
      validIds.has(id) ? id : "unverified artifact",
    )
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  const uncited = artifactIds.filter((id) => !safeAnswer.includes(id));
  return uncited.length ? `${safeAnswer}\n\nArtifacts: ${uncited.join(", ")}` : safeAnswer;
}

async function createFallbackReport(
  context: AgentContext,
  prompt: string,
  draft?: string,
): Promise<string> {
  const datasetId = prompt.match(/\bds_[a-zA-Z0-9]{12}\b/)?.[0];
  if (!datasetId) throw new Error("Report fallback requires a persisted dataset ID");
  const chartId = prompt.match(/\bch_[a-zA-Z0-9]{12}\b/)?.[0];
  if (!chartId) throw new Error("Report fallback requires a persisted chart ID from Visualize");
  const scope = runtimeScope(context);
  const description = (await context.pool.call(
    "warehouse.describe_dataset",
    { datasetId },
    scope,
    "report",
  )) as {
    name: string;
    columns: Array<{ name: string; type: string }>;
  };
  const result = (await context.pool.call(
    "warehouse.get_dataset_rows",
    { datasetId, limit: 20 },
    scope,
    "report",
  )) as { rows: Array<Record<string, unknown>> };
  const title = `${description.name} analysis`;
  const table = [
    `| ${description.columns.map(({ name }) => name).join(" | ")} |`,
    `| ${description.columns.map(() => "---").join(" | ")} |`,
    ...result.rows
      .slice(0, 10)
      .map(
        (row) => `| ${description.columns.map(({ name }) => formatCell(row[name])).join(" | ")} |`,
      ),
  ].join("\n");
  const compare = extractSpecialistResult(prompt, "compare");
  const insight = extractSpecialistResult(prompt, "insight");
  const visualize = extractSpecialistResult(prompt, "visualize");
  const reportDraft = draft?.trim().slice(0, 10_000);
  const markdown = [
    `# ${title}`,
    "",
    `Source dataset: {{dataset:${datasetId}}}`,
    "",
    "## Comparison",
    "",
    compare,
    "",
    "## Insight",
    "",
    insight,
    "",
    "## Visualization",
    "",
    visualize,
    "",
    `{{chart:${chartId}}}`,
    "",
    ...(reportDraft ? ["## Report", "", reportDraft, ""] : []),
    "## Data preview",
    "",
    table,
    "",
    "The report summarizes the supplied specialist findings and persisted dataset. No causal explanation is asserted.",
  ].join("\n");
  const report = (await context.pool.call(
    "warehouse.save_report",
    { title, markdown },
    scope,
    "report",
  )) as { id: string };
  return `Report ${report.id} saved with chart ${chartId} from dataset ${datasetId}.`;
}

async function createFallbackVisualization(context: AgentContext, prompt: string): Promise<string> {
  const datasetId = prompt.match(/\bds_[a-zA-Z0-9]{12}\b/)?.[0];
  if (!datasetId) throw new Error("Visualize fallback requires a persisted dataset ID");
  const scope = runtimeScope(context);
  const description = (await context.pool.call(
    "warehouse.describe_dataset",
    { datasetId },
    scope,
    "visualize",
  )) as { name: string; columns: Array<{ name: string; type: string }> };
  const x =
    description.columns.find(({ name }) => /month|date|region|category|segment/i.test(name)) ??
    description.columns.find(({ type }) => !/number|integer|float|decimal/i.test(type));
  const y = description.columns.find(({ type }) => /number|integer|float|decimal/i.test(type));
  if (!x || !y) throw new Error("Visualize fallback could not find chart dimensions");
  const comparison = extractSpecialistResult(prompt, "compare");
  const insight = extractSpecialistResult(prompt, "insight");
  const title = `${description.name}: ${shortFinding(comparison || insight || `${y.name} by ${x.name}`)}`;
  const chart = (await context.pool.call(
    "warehouse.create_chart",
    {
      datasetId,
      kind: /month|date/i.test(x.name) ? "line" : "bar",
      x: x.name,
      y: y.name,
      title: title.slice(0, 200),
    },
    scope,
    "visualize",
  )) as { id: string };
  return `Created chart ${chart.id} using ${x.name} and ${y.name}.`;
}

function extractSpecialistResult(prompt: string, agent: string): string {
  const escaped = agent.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return (
    prompt
      .match(new RegExp(`\\[${escaped}\\]\\n([\\s\\S]*?)(?=\\n\\n\\[[a-z]+\\]\\n|$)`))?.[1]
      ?.trim() ?? "No result supplied."
  );
}

function shortFinding(value: string): string {
  return value
    .replace(/\s+/g, " ")
    .replace(/\b(?:ds|ch|rp)_[a-zA-Z0-9]{12}\b/g, "")
    .slice(0, 120);
}

function formatCell(value: unknown): string {
  return String(value ?? "")
    .replaceAll("|", "\\|")
    .replaceAll("\n", " ");
}

function delegateTo(context: AgentContext, agent: string, message: string): Promise<unknown> {
  return context.pool.call(
    "agents.delegate",
    { agent, message },
    runtimeScope(context),
    "orchestrator",
  );
}

function delegateToCapability(
  context: AgentContext,
  capability: string,
  message: string,
): Promise<unknown> {
  return context.pool.call(
    "agents.delegate",
    { capability, message },
    runtimeScope(context),
    "orchestrator",
  );
}

function stringifyResult(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function clip(value: string, maxLength: number): string {
  return value.length <= maxLength ? value : `${value.slice(0, maxLength)} [truncated]`;
}

function extractDatasetId(evidence: unknown): string | undefined {
  if (!isRecord(evidence) || !isRecord(evidence.dataset)) return undefined;
  const id = evidence.dataset.dataset_id;
  return typeof id === "string" && /^ds_[a-zA-Z0-9]{12}$/.test(id) ? id : undefined;
}

function isAnalyticsRequest(prompt: string): boolean {
  return /monthly_sales|\b(?:sales|revenue|warehouse|dataset|table|data|compare|comparison|trend|analy[sz]e|analysis|chart|report|region|profit|growth|month|quarter|year)\b|doanh thu|báo cáo|so sánh|phân tích|biểu đồ|dữ liệu|bảng/i.test(
    prompt,
  );
}

function needsComparison(prompt: string): boolean {
  return /\b(?:compare|comparison|versus|vs|change|delta|growth|rank|difference)\b|so sánh|chênh lệch|tăng|giảm|thay đổi/i.test(
    prompt,
  );
}

function needsInsight(prompt: string): boolean {
  return /\b(?:explain|why|trend|pattern|driver|insight|analy[sz]e|analysis)\b|giải thích|xu hướng|phân tích|nguyên nhân/i.test(
    prompt,
  );
}

function needsReport(prompt: string): boolean {
  return /\b(?:report|chart|visuali[sz]e|save|write-up)\b|báo cáo|biểu đồ|lưu lại/i.test(prompt);
}

async function prepareNamedTable(context: AgentContext, prompt: string): Promise<unknown> {
  const scope = {
    agentId: "data",
    userId: context.userId,
    spaceId: context.spaceId,
    sessionId: context.sessionId,
    runId: context.runId,
    taskId: context.taskId,
    depth: context.depth,
    publish: context.publish,
    trace: context.trace,
    signal: context.signal,
  };
  const sources = (await context.pool.call("warehouse.list_sources", {}, scope, "data")) as {
    warehouses?: Array<{ id: string; name: string }>;
  };
  const warehouse =
    sources.warehouses?.find((source) => prompt.toLowerCase().includes(source.id.toLowerCase())) ??
    sources.warehouses?.[0];
  if (!warehouse) return { error: "No warehouse provider is registered" };

  const tableResult = (await context.pool.call(
    "warehouse.list_tables",
    { warehouseId: warehouse.id },
    scope,
    "data",
  )) as { tables?: Array<{ name: string; rowCount: number }> };
  const table = tableResult.tables?.find(({ name }) =>
    prompt.toLowerCase().includes(name.toLowerCase()),
  );
  if (!table) return { warehouse: warehouse.name, tables: tableResult.tables ?? [] };

  const [description, dataset] = await Promise.all([
    context.pool.call(
      "warehouse.describe_table",
      { warehouseId: warehouse.id, table: table.name },
      scope,
      "data",
    ),
    context.pool.call(
      "warehouse.run_query",
      { warehouseId: warehouse.id, table: table.name, limit: 100 },
      scope,
      "data",
    ),
  ]);
  if (!isRecord(dataset) || typeof dataset.dataset_id !== "string" || !dataset.dataset_id) {
    throw new Error("Warehouse query did not return a persisted dataset ID");
  }
  return { warehouse, table: description, dataset };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function runtimeScope(context: AgentContext) {
  return {
    userId: context.userId,
    spaceId: context.spaceId,
    sessionId: context.sessionId,
    runId: context.runId,
    taskId: context.taskId,
    depth: context.depth,
    publish: context.publish,
    signal: context.signal,
  };
}
