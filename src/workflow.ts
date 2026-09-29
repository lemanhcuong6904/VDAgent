import type { TSchema } from "typebox";

export interface WorkflowStepSpec {
  id: string;
  capability: string;
  inputSchema?: TSchema;
  outputSchema?: TSchema;
  dependsOn?: readonly string[];
}

export interface WorkflowSpec {
  id: string;
  version: string;
  triggerSchema: TSchema;
  stateSchema: TSchema;
  steps: readonly WorkflowStepSpec[];
  requiredCapabilities?: readonly string[];
  maxDurationMs?: number;
  maxAttempts?: number;
}

export class WorkflowRegistry {
  private readonly specs = new Map<string, WorkflowSpec>();

  register(spec: WorkflowSpec): void {
    validateWorkflowSpec(spec);
    const key = `${spec.id}@${spec.version}`;
    if (this.specs.has(key)) throw new Error(`Workflow '${key}' is already registered`);
    this.specs.set(key, { ...spec, steps: spec.steps.map((step) => ({ ...step })) });
  }

  get(id: string, version?: string): WorkflowSpec | undefined {
    if (version) return this.specs.get(`${id}@${version}`);
    return [...this.specs.values()].filter((spec) => spec.id === id).at(-1);
  }

  list(): WorkflowSpec[] {
    return [...this.specs.values()].map((spec) => ({
      ...spec,
      steps: spec.steps.map((step) => ({ ...step })),
    }));
  }
}

export function validateWorkflowSpec(spec: WorkflowSpec): void {
  if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(spec.id)) {
    throw new Error(`Invalid workflow id '${spec.id}'`);
  }
  if (!spec.version.trim()) throw new Error(`Workflow '${spec.id}' needs a version`);
  if (spec.steps.length === 0 || spec.steps.length > 128) {
    throw new Error(`Workflow '${spec.id}' must contain 1-128 steps`);
  }
  const ids = new Set<string>();
  for (const step of spec.steps) {
    if (!/^[a-z0-9][a-z0-9._-]{0,127}$/.test(step.id)) {
      throw new Error(`Invalid workflow step '${step.id}'`);
    }
    if (ids.has(step.id)) throw new Error(`Workflow '${spec.id}' has duplicate step '${step.id}'`);
    ids.add(step.id);
    if (!step.capability.trim()) throw new Error(`Workflow step '${step.id}' needs a capability`);
  }
  for (const step of spec.steps) {
    for (const dependency of step.dependsOn ?? []) {
      if (!ids.has(dependency)) {
        throw new Error(`Workflow step '${step.id}' depends on unknown step '${dependency}'`);
      }
    }
  }
  assertAcyclic(spec.steps);
}

function assertAcyclic(steps: readonly WorkflowStepSpec[]): void {
  const byId = new Map(steps.map((step) => [step.id, step]));
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (id: string) => {
    if (visiting.has(id)) throw new Error("Workflow steps must form an acyclic graph");
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dependency of byId.get(id)?.dependsOn ?? []) visit(dependency);
    visiting.delete(id);
    visited.add(id);
  };
  for (const step of steps) visit(step.id);
}
