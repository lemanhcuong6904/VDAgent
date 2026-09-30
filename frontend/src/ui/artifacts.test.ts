import { describe, expect, it } from "vitest";
import { ARTIFACT_EXACT, ARTIFACT_SPLIT, artifactIds, artifactKind } from "./artifacts";

describe("artifact id helpers", () => {
  it("recognizes shared-store art ids as chart artifacts for chart_spec previews", () => {
    expect("Biểu đồ: art_bfcf653b9f09".split(ARTIFACT_SPLIT)).toEqual(["Biểu đồ: ", "art_bfcf653b9f09", ""]);
    expect(ARTIFACT_EXACT.test("art_bfcf653b9f09")).toBe(true);
    expect(artifactKind("art_bfcf653b9f09")).toBe("chart");
  });

  it("extracts distinct artifact ids from task text", () => {
    expect(artifactIds("art_bfcf653b9f09 ds_000000000001 art_bfcf653b9f09 rp_000000000002")).toEqual([
      "art_bfcf653b9f09",
      "ds_000000000001",
      "rp_000000000002",
    ]);
  });
});
