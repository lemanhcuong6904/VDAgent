import { describe, expect, it } from "vitest";
import { explainWarning, parseStepSpec, plainPreview, reportTone, splitAgentReport } from "./agentReport";

const REPORT = {
  contract: "AgentReport@1",
  run_id: "t_1",
  step_id: "B1",
  idempotency_key: "pl_1:B1",
  state: "completed",
  partial: true,
  artifact_refs: [
    { artifact_id: "art_5706487b54f2", version: 1, artifact_type: "dataset", content_hash: "1b5815f9" },
    { artifact_id: "art_6640c53b5580", version: 1, artifact_type: "metric", content_hash: "8022ddf1" },
  ],
  snapshot_id: "SNAP-20260630-01",
  semantic_config_version: "3.1.0",
  summary: "Data đã tạo 2 artifact.",
  warnings: ["METRIC_UNAVAILABLE:discount_pct"],
  error: null,
  question: null,
};
const fence = (value: unknown) => "```json\n" + JSON.stringify(value, null, 2) + "\n```";

describe("splitAgentReport", () => {
  it("keeps the closing line as markdown and turns the JSON fence into a report", () => {
    const text = `Xong: đã lưu 2 gói.\n\n${fence(REPORT)}`;
    const segments = splitAgentReport(text);
    expect(segments).toHaveLength(2);
    expect(segments[0]).toEqual({ kind: "markdown", text: "Xong: đã lưu 2 gói.\n\n" });
    expect(segments[1]).toMatchObject({ kind: "report", report: { state: "completed", partial: true, step_id: "B1" } });
    expect(segments[1]).toHaveProperty("raw");
  });

  it("leaves text without a fence alone", () => {
    expect(splitAgentReport("chỉ là văn bản")).toEqual([{ kind: "markdown", text: "chỉ là văn bản" }]);
    expect(splitAgentReport("")).toEqual([]);
  });

  it("does not touch a JSON fence that is not an AgentReport", () => {
    const text = `ví dụ\n\n${fence({ hello: "world" })}`;
    expect(splitAgentReport(text)).toEqual([{ kind: "markdown", text }]);
  });

  it("does not touch a fence that is not valid JSON or lacks the fields of a report", () => {
    const broken = "```json\n{ not json\n```";
    expect(splitAgentReport(broken)).toEqual([{ kind: "markdown", text: broken }]);
    const partial = fence({ contract: "AgentReport@1" });
    expect(splitAgentReport(partial)).toEqual([{ kind: "markdown", text: partial }]);
  });

  it("finds the report among other fences and keeps their order", () => {
    const other = "```sql\nSELECT 1\n```";
    const segments = splitAgentReport(`a\n${other}\nb\n${fence(REPORT)}\nc`);
    expect(segments.map((s) => s.kind)).toEqual(["markdown", "report", "markdown"]);
    expect(segments[0]).toEqual({ kind: "markdown", text: `a\n${other}\nb\n` });
    expect(segments[2]).toEqual({ kind: "markdown", text: "\nc" });
  });

  it("reads a fence with Windows line endings", () => {
    const text = `x\r\n\`\`\`json\r\n${JSON.stringify(REPORT)}\r\n\`\`\``;
    expect(splitAgentReport(text).map((s) => s.kind)).toEqual(["markdown", "report"]);
  });

  it("reads a report that failed, with its error and question", () => {
    const failed = { ...REPORT, state: "failed", partial: false, artifact_refs: [], error: { code: "UNIT_NOT_FOUND", message: "không thấy", retryable: false } };
    const [segment] = splitAgentReport(fence(failed));
    expect(segment).toMatchObject({ kind: "report", report: { state: "failed", error: { code: "UNIT_NOT_FOUND" } } });
    const ask = { ...REPORT, state: "input_required", question: { text: "Căn nào?", options: [{ id: "a", label: "A" }] } };
    expect(splitAgentReport(fence(ask))[0]).toMatchObject({ report: { question: { options: [{ id: "a", label: "A" }] } } });
  });
});

describe("reportTone", () => {
  it("tells done, partial, failed and asking apart", () => {
    const base = splitAgentReport(fence(REPORT));
    if (base[0]?.kind !== "report") throw new Error("expected a report");
    const r = base[0].report;
    expect(reportTone({ ...r, state: "completed", partial: false })).toBe("ok");
    expect(reportTone({ ...r, state: "completed", partial: true })).toBe("partial");
    expect(reportTone({ ...r, state: "failed" })).toBe("error");
    expect(reportTone({ ...r, state: "rejected" })).toBe("error");
    expect(reportTone({ ...r, state: "input_required" })).toBe("ask");
    expect(reportTone({ ...r, state: "canceled" })).toBe("error");
  });
});

describe("explainWarning", () => {
  it("explains the limitation codes Data produces, naming the field", () => {
    expect(explainWarning("METRIC_UNAVAILABLE:discount_pct")).toMatchObject({ code: "METRIC_UNAVAILABLE", target: "discount_pct" });
    expect(explainWarning("METRIC_UNAVAILABLE:discount_pct").text).toContain("discount_pct");
    expect(explainWarning("WINDOW_INCOMPLETE:inquiry_leads_30d:3").text).toContain("3");
    expect(explainWarning("DQ_MISSING:net_price_per_m2:2").text).toContain("net_price_per_m2");
    expect(explainWarning("CONFIG_PENDING:min_group_size").text).toContain("min_group_size");
    expect(explainWarning("SYNTHETIC_SOURCE:net_area_m2").text).toContain("net_area_m2");
    expect(explainWarning("BLOCKED:D2b_segment_mapping").text).toContain("D2b_segment_mapping");
  });

  it("shows a code it does not know as it is", () => {
    expect(explainWarning("FOO:bar")).toEqual({ code: "FOO", target: "bar", text: "FOO:bar" });
    expect(explainWarning("PLAIN")).toEqual({ code: "PLAIN", target: "", text: "PLAIN" });
  });
});

describe("plainPreview", () => {
  const step = JSON.stringify({
    contract: "StepSpec@1", step_id: "B1", operation: "fetch_units", spec: { subject_unit_code: "OCP-U00001" },
    original_question: "Vì sao căn OCP-U00001 bán chậm?",
  });

  it("says what a StepSpec asks instead of showing its JSON", () => {
    expect(plainPreview(step)).toBe("B1 · fetch_units — Vì sao căn OCP-U00001 bán chậm?");
    expect(plainPreview(`[from: orchestrator] ${step}`)).toBe("B1 · fetch_units — Vì sao căn OCP-U00001 bán chậm?");
  });

  it("keeps the closing line of an answer and drops its JSON fence", () => {
    expect(plainPreview(`Xong: đã lưu 2 gói.\n\n${fence(REPORT)}`)).toBe("Xong: đã lưu 2 gói.");
  });

  it("falls back to the summary, then the state, when there is no closing line", () => {
    expect(plainPreview(fence(REPORT))).toBe("Data đã tạo 2 artifact.");
    expect(plainPreview(fence({ ...REPORT, summary: "" }))).toBe("completed");
  });

  it("leaves ordinary text as it is", () => {
    expect(plainPreview("Vì sao căn A12-08 bán chậm?")).toBe("Vì sao căn A12-08 bán chậm?");
    expect(plainPreview("")).toBe("");
  });
});

describe("parseStepSpec", () => {
  const STEP = {
    contract: "StepSpec@1",
    run_id: "t_1",
    plan_id: "pl_1",
    step_id: "B1",
    idempotency_key: "pl_1:B1",
    operation: "fetch_units",
    spec: { subject_unit_code: "OCP-U00001", population: "peer_candidates" },
    user_context: { user_id: "u_1", authorized_scope: { project_ids: ["100", "400"], zone_ids: [] } },
    snapshot_id: "SNAP-20260630-01",
    semantic_config_version: "3.1.0",
    input_refs: [],
    deadline_s: 60,
    original_question: "Vì sao căn OCP-U00001 bán chậm?",
  };

  it("reads what the Orchestrator asked", () => {
    expect(parseStepSpec(JSON.stringify(STEP))).toMatchObject({
      operation: "fetch_units",
      stepId: "B1",
      question: "Vì sao căn OCP-U00001 bán chậm?",
      snapshot: "SNAP-20260630-01",
      semantic: "3.1.0",
      deadlineS: 60,
      scopeProjects: ["100", "400"],
      spec: [["subject_unit_code", "OCP-U00001"], ["population", "peer_candidates"]],
    });
  });

  it("ignores the [from: agent] prefix and anything that is not a StepSpec", () => {
    expect(parseStepSpec(`[from: orchestrator] ${JSON.stringify(STEP)}`)?.operation).toBe("fetch_units");
    expect(parseStepSpec("Vì sao căn A12-08 bán chậm?")).toBeNull();
    expect(parseStepSpec(JSON.stringify({ contract: "ChartTask@1" }))).toBeNull();
    expect(parseStepSpec("{ not json")).toBeNull();
  });

  it("shows list and object values of the spec as readable text", () => {
    const view = parseStepSpec(JSON.stringify({ ...STEP, spec: { metrics: ["dom_days", "asking_price_vnd"], filters: { zone_key: "Z1" } } }));
    expect(view?.spec).toEqual([["metrics", "dom_days, asking_price_vnd"], ["filters", "zone_key = Z1"]]);
  });
});
