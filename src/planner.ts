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
