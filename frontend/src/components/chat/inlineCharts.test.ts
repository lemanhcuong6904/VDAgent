import { describe, expect, it } from "vitest";
import { inlineChartSpecs } from "./inlineCharts";

describe("inlineChartSpecs", () => {
  it("does not create inline previews from orchestrator chart summaries", () => {
    const text =
      "Bieu do: art_bfcf653b9f09, art_d345be722b4e, art_bfcf653b9f09\n" +
      "B4 chart.draw_chart hoan tat art_f10a8776c51f";

    expect(inlineChartSpecs(text)).toEqual([]);
  });

  it("does not create inline previews even when a message mentions many chart artifacts", () => {
    expect(
      inlineChartSpecs(
        "Bieu do: art_000000000001 art_000000000002 art_000000000003 art_000000000004 art_000000000005 art_000000000006",
      ),
    ).toEqual([]);
  });
});
