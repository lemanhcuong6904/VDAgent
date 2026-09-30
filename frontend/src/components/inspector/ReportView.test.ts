import { describe, expect, it } from "vitest";
import { splitReport } from "./ReportView";

describe("splitReport", () => {
  it("turns a pinned chart_spec embed into a renderable segment", () => {
    expect(splitReport("before\n\n{{chart_spec:art_abc@3}}\n\nafter")).toEqual([
      { kind: "markdown", text: "before\n\n" },
      { kind: "chart_spec", id: "art_abc", version: 3 },
      { kind: "markdown", text: "\n\nafter" },
    ]);
  });

  it("keeps legacy chart and dataset embeds compatible", () => {
    expect(splitReport("{{chart:ch_1}} {{dataset:ds_1}}")).toEqual([
      { kind: "chart", id: "ch_1" },
      { kind: "dataset", id: "ds_1" },
    ]);
  });
});
