export interface InlineChartSpec {
  id: string;
  version: number;
}

/** Inline chart previews are disabled; charts are opened from the Artifacts panel instead. */
export function inlineChartSpecs(_text: string): InlineChartSpec[] {
  return [];
}
