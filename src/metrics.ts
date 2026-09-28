type MetricType = "counter" | "histogram";

interface MetricValue {
  type: MetricType;
  value: number;
}

const values = new Map<string, MetricValue>();

export function incrementMetric(
  name: string,
  value = 1,
  labels: Record<string, unknown> = {},
): void {
  updateMetric(name, "counter", value, labels);
}

export function observeMetric(
  name: string,
  value: number,
  labels: Record<string, unknown> = {},
): void {
  updateMetric(name, "histogram", value, labels);
}

export function renderPrometheus(): string {
  const lines: string[] = [];
  for (const [key, metric] of values) {
    const [name, encodedLabels] = key.split("|", 2);
    const labels = encodedLabels ? `{${encodedLabels}}` : "";
    lines.push(`${name}${labels} ${metric.value}`);
  }
  return `${lines.join("\n")}\n`;
}

export function resetMetrics(): void {
  values.clear();
}

function updateMetric(
  name: string,
  type: MetricType,
  value: number,
  labels: Record<string, unknown>,
): void {
  const normalized = normalizeName(name);
  if (!normalized || !Number.isFinite(value)) return;
  const key = `${normalized}|${encodeLabels(labels)}`;
  const current = values.get(key);
  if (current && current.type !== type) return;
  values.set(key, { type, value: (current?.value ?? 0) + value });
}

function normalizeName(name: string): string {
  const normalized = name.replace(/[^a-zA-Z0-9_:]/g, "_");
  return /^[a-zA-Z_:]/.test(normalized) ? normalized : `vdagent_${normalized}`;
}

function encodeLabels(labels: Record<string, unknown>): string {
  return Object.entries(labels)
    .filter(
      ([key, value]) =>
        /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(key) &&
        !/(prompt|content|memory|token|secret|user|space|query|row)/i.test(key) &&
        scalar(value),
    )
    .slice(0, 8)
    .map(([key, value]) => `${key}="${escapeLabel(String(value).slice(0, 80))}"`)
    .join(",");
}

function scalar(value: unknown): boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function escapeLabel(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"').replaceAll("\n", "\\n");
}
