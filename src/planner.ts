export interface PlannerAgent {
  id: string;
  version: string;
  description: string;
  capabilities: readonly string[];
}

export interface PlannerCatalog {
  findByCapability(capability: string): readonly PlannerAgent[];
}

export interface PlanStep {
  id: string;
  capability: string;
  agentId: string;
  dependsOn: string[];
}

export interface PlanSpec {
  version: "plan.v1";
  goal: string;
  steps: PlanStep[];
  assumptions?: string[];
  clarification?: string;
  budget?: { maxSteps?: number; maxDurationMs?: number; maxTokens?: number };
}

export class MissingCapabilityError extends Error {
  constructor(readonly capability: string) {
    super(`No agent provides capability '${capability}'`);
    this.name = "MissingCapabilityError";
  }
}

const DATA_INTENT =
  /\b(?:data|dataset|table|warehouse|sales|revenue|profit|customer|metric|kpi|trend|compare|comparison|versus|vs|chart|visuali[sz]e|report|analysis|analy[sz]e|growth|month|quarter|year)\b|doanh thu|báo cáo|so sánh|phân tích|biểu đồ|dữ liệu|bảng/i;

export function buildCapabilityPlan(prompt: string, catalog: PlannerCatalog): PlanSpec | undefined {
  if (!DATA_INTENT.test(prompt)) return undefined;
  const requested = ["warehouse.query"];
  if (
    /\b(?:compare|comparison|versus|vs|change|delta|growth|rank|difference)\b|so sánh|chênh lệch|tăng|giảm|thay đổi/i.test(
      prompt,
    )
  ) {
    requested.push("dataset.compare");
  }
  if (
    /\b(?:explain|why|trend|pattern|driver|insight|analy[sz]e|analysis)\b|giải thích|xu hướng|phân tích|nguyên nhân/i.test(
      prompt,
    )
  ) {
    requested.push("dataset.insight");
  }
  if (/\b(?:chart|visuali[sz]e|report|write-up)\b|biểu đồ|báo cáo|lưu lại/i.test(prompt)) {
    requested.push("dataset.visualize");
  }
  if (/\b(?:report|write-up|save)\b|báo cáo|lưu lại/i.test(prompt))
    requested.push("dataset.report");

  const steps: PlanStep[] = [];
  for (const capability of requested) {
    const candidate = catalog.findByCapability(capability)[0];
    if (!candidate) throw new MissingCapabilityError(capability);
    steps.push({
      id: capability.replaceAll(".", "_"),
      capability,
      agentId: candidate.id,
      dependsOn: steps.length ? [steps.at(-1)?.id ?? ""] : [],
    });
  }
  return { version: "plan.v1", goal: prompt, steps };
}

export function validatePlan(plan: PlanSpec, catalog: PlannerCatalog): PlanSpec {
  if (plan.version !== "plan.v1" || !plan.goal.trim())
    throw new Error("Invalid plan version or goal");
  if (plan.steps.length > 32) throw new Error("Plan exceeds the maximum step count");
  const ids = new Set<string>();
  for (const step of plan.steps) {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(step.id) || ids.has(step.id)) {
      throw new Error(`Plan contains an invalid or duplicate step '${step.id}'`);
    }
    ids.add(step.id);
    const candidate = catalog
      .findByCapability(step.capability)
      .find((agent) => agent.id === step.agentId);
    if (!candidate) throw new MissingCapabilityError(step.capability);
    for (const dependency of step.dependsOn) {
      if (!ids.has(dependency)) throw new Error(`Plan step '${step.id}' has an invalid dependency`);
    }
  }
  return {
    ...plan,
    assumptions: plan.assumptions?.slice(0, 32),
    budget: plan.budget ? { ...plan.budget } : undefined,
    steps: plan.steps.map((step) => ({ ...step, dependsOn: [...step.dependsOn] })),
  };
}

export async function proposeCapabilityPlan(
  prompt: string,
  catalog: PlannerCatalog,
  propose: (catalogDescription: string) => Promise<string>,
): Promise<PlanSpec | undefined> {
  const catalogDescription = catalog
    .findByCapability("*")
    .map((agent) => `${agent.id}@${agent.version}: ${agent.capabilities.join(", ")}`)
    .join("\n");
  const raw = await propose(catalogDescription);
  const parsed = parsePlan(raw);
  return parsed ? validatePlan({ ...parsed, goal: prompt }, catalog) : undefined;
}

function parsePlan(raw: string): PlanSpec | undefined {
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1] ?? raw;
  try {
    const value = JSON.parse(fenced.trim()) as Partial<PlanSpec>;
    if (
      value.version !== "plan.v1" ||
      !Array.isArray(value.steps) ||
      value.steps.some(
        (step) =>
          !step ||
          typeof step !== "object" ||
          typeof step.id !== "string" ||
          typeof step.capability !== "string" ||
          typeof step.agentId !== "string" ||
          !Array.isArray(step.dependsOn),
      )
    ) {
      return undefined;
    }
    return value as PlanSpec;
  } catch {
    return undefined;
  }
}
