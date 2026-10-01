/**
 * The machine messages between agents, read for people.
 *
 * An agent answers an Orchestrator step with a closing line and one ```json fence holding an `AgentReport@1`; the
 * Orchestrator sends a `StepSpec@1` as plain JSON. These helpers find them in a message so the chat can show a card
 * instead of raw JSON (the JSON stays one click away). Pure functions: nothing here touches the DOM.
 */

export interface ArtifactRefView {
  artifact_id: string;
  version: number;
  artifact_type: string;
  content_hash: string | null;
}

export interface AgentReportView {
  state: string;
  partial: boolean;
  run_id: string | null;
  step_id: string | null;
  artifact_refs: ArtifactRefView[];
  snapshot_id: string | null;
  semantic_config_version: string | null;
  summary: string;
  warnings: string[];
  error: { code: string; message: string; retryable: boolean } | null;
  question: { text: string; options: { id: string; label: string }[] } | null;
  data_confidence: string | null;
}

export type Segment =
  | { kind: "markdown"; text: string }
  | { kind: "report"; report: AgentReportView; raw: string };

export type Tone = "ok" | "partial" | "error" | "ask";

const FENCE = /```json[ \t]*\r?\n([\s\S]*?)\r?\n[ \t]*```/g;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

function toReport(value: unknown): AgentReportView | null {
  if (!isObject(value) || value.contract !== "AgentReport@1" || typeof value.state !== "string") return null;
  const refs = Array.isArray(value.artifact_refs) ? value.artifact_refs : [];
  const error = isObject(value.error) ? value.error : null;
  const question = isObject(value.question) ? value.question : null;
  return {
    state: value.state,
    partial: value.partial === true,
    run_id: text(value.run_id),
    step_id: text(value.step_id),
    artifact_refs: refs.filter(isObject).map((r) => ({
      artifact_id: String(r.artifact_id ?? ""),
      version: Number(r.version ?? 0),
      artifact_type: String(r.artifact_type ?? ""),
      content_hash: text(r.content_hash),
    })),
    snapshot_id: text(value.snapshot_id),
    semantic_config_version: text(value.semantic_config_version),
    summary: text(value.summary) ?? "",
    warnings: Array.isArray(value.warnings) ? value.warnings.filter((w): w is string => typeof w === "string") : [],
    error: error ? { code: String(error.code ?? ""), message: String(error.message ?? ""), retryable: error.retryable === true } : null,
    question: question
      ? {
          text: String(question.text ?? ""),
          options: (Array.isArray(question.options) ? question.options : []).filter(isObject).map((o) => ({
            id: String(o.id ?? ""),
            label: String(o.label ?? ""),
          })),
        }
      : null,
    data_confidence: text(value.data_confidence),
  };
}

/** Cut a message at its `AgentReport@1` fence: markdown, report, markdown. Other fences stay in the markdown. */
export function splitAgentReport(message: string): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  for (const match of message.matchAll(FENCE)) {
    let report: AgentReportView | null = null;
    try {
      report = toReport(JSON.parse(match[1] ?? ""));
    } catch {
      report = null;
    }
    if (!report || match.index === undefined) continue;
    if (match.index > cursor) segments.push({ kind: "markdown", text: message.slice(cursor, match.index) });
    segments.push({ kind: "report", report, raw: JSON.stringify(JSON.parse(match[1] ?? "{}"), null, 2) });
    cursor = match.index + match[0].length;
  }
  if (cursor < message.length) segments.push({ kind: "markdown", text: message.slice(cursor) });
  return segments;
}

export function reportTone(report: Pick<AgentReportView, "state" | "partial">): Tone {
  if (report.state === "input_required") return "ask";
  if (report.state === "completed") return report.partial ? "partial" : "ok";
  return "error";
}

export interface WarningView {
  code: string;
  target: string;
  text: string;
}

/** A limitation code such as `METRIC_UNAVAILABLE:discount_pct` in plain Vietnamese; a code it does not know stays as it is. */
export function explainWarning(warning: string): WarningView {
  const [code = "", target = "", ...rest] = warning.split(":");
  const n = rest[0] ?? "";
  const known: Record<string, string> = {
    METRIC_UNAVAILABLE: `Chỉ số ${target} không có nguồn trong kho nên để trống (không điền 0).`,
    WINDOW_INCOMPLETE: `${target}: kho mới phủ ${n} ngày của cửa sổ cần dùng nên không tổng hợp.`,
    DQ_MISSING: `Trường ${target} thiếu giá trị ở ${n} căn.`,
    CONFIG_PENDING: `Ngưỡng ${target} chưa được duyệt; giữ nguyên, không dùng giá trị mặc định.`,
    SYNTHETIC_SOURCE: `Trường ${target} được ghi nhận là dữ liệu mô phỏng.`,
    BLOCKED: `${target} đang chờ quyết định nghiệp vụ nên chưa áp dụng.`,
    PEER_AREA_UNAVAILABLE: `${target} căn ứng viên bị loại vì thiếu diện tích thực.`,
    QUALITY_GATE_UNAVAILABLE: "Cổng kiểm tra chất lượng đang tạm thời không kết nối được.",
  };
  return { code, target, text: known[code] ?? warning };
}

// ---- the step the Orchestrator sent ----------------------------------------------------------------------------------

export interface StepSpecView {
  operation: string;
  stepId: string;
  question: string;
  snapshot: string | null;
  semantic: string | null;
  deadlineS: number | null;
  scopeProjects: string[];
  spec: [string, string][];
  raw: string;
}

function readable(value: unknown): string {
  if (Array.isArray(value)) return value.map(readable).join(", ");
  if (isObject(value)) return Object.entries(value).map(([k, v]) => `${k} = ${readable(v)}`).join(", ");
  return String(value);
}

/** The `StepSpec@1` in a message (an optional `[from: agent]` prefix is ignored), or null for anything else. */
export function parseStepSpec(message: string): StepSpecView | null {
  const body = message.replace(/^\[from: [^\]]+\]\s*/, "").trim();
  if (!body.startsWith("{")) return null;
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    return null;
  }
  if (!isObject(value) || value.contract !== "StepSpec@1") return null;
  const context = isObject(value.user_context) ? value.user_context : {};
  const scope = isObject(context.authorized_scope) ? context.authorized_scope : {};
  return {
    operation: String(value.operation ?? ""),
    stepId: String(value.step_id ?? ""),
    question: String(value.original_question ?? ""),
    snapshot: text(value.snapshot_id),
    semantic: text(value.semantic_config_version),
    deadlineS: typeof value.deadline_s === "number" ? value.deadline_s : null,
    scopeProjects: Array.isArray(scope.project_ids) ? scope.project_ids.map(String) : [],
    spec: isObject(value.spec) ? Object.entries(value.spec).map(([k, v]): [string, string] => [k, readable(v)]) : [],
    raw: JSON.stringify(value, null, 2),
  };
}

/** One line for a list or tree: what a StepSpec asks, or the closing line of an answer, never the JSON. */
export function plainPreview(message: string): string {
  const step = parseStepSpec(message);
  if (step) return `${step.stepId} · ${step.operation}${step.question ? ` — ${step.question}` : ""}`;
  const segments = splitAgentReport(message);
  const report = segments.find((s) => s.kind === "report");
  if (!report || report.kind !== "report") return message;
  const before = segments
    .filter((s) => s.kind === "markdown")
    .map((s) => s.text.trim())
    .filter(Boolean)
    .join(" ");
  return before || report.report.summary || report.report.state;
}
