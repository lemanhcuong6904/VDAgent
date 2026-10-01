import type { RunGraphNodeDTO, RunViewDTO, UsageTotalsDTO } from "../api/types";

/** Graph nodes in reading order: roots first, then breadth-first along edges; orphans last. */
export function orderGraph(graph: RunViewDTO["graph"]): { node: RunGraphNodeDTO; depth: number }[] {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const children = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const list = children.get(edge.from) ?? [];
    list.push(edge.to);
    children.set(edge.from, list);
  }
  const ordered: { node: RunGraphNodeDTO; depth: number }[] = [];
  const seen = new Set<string>();
  const queue = graph.roots.filter((id) => byId.has(id)).map((id) => ({ id, depth: 0 }));
  while (queue.length > 0) {
    const next = queue.shift();
    if (!next || seen.has(next.id)) continue;
    const node = byId.get(next.id);
    if (!node) continue;
    seen.add(next.id);
    ordered.push({ node, depth: next.depth });
    for (const child of children.get(next.id) ?? [])
      queue.push({ id: child, depth: next.depth + 1 });
  }
  // A node the server reports but no edge reaches is still shown, never silently dropped.
  for (const node of graph.nodes) if (!seen.has(node.id)) ordered.push({ node, depth: 0 });
  return ordered;
}

const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

export function formatCost(value: number): string {
  return Number.isFinite(value) ? usd.format(value) : "—";
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${String(Math.floor((ms % 60_000) / 1000)).padStart(2, "0")}s`;
}

/** Cost rows sorted most expensive first, so the reader sees what drove the total. */
export function costRows(
  group: Record<string, UsageTotalsDTO>,
): { key: string; totals: UsageTotalsDTO }[] {
  return Object.entries(group)
    .map(([key, totals]) => ({ key, totals }))
    .sort(
      (left, right) =>
        right.totals.estimatedCost - left.totals.estimatedCost || left.key.localeCompare(right.key),
    );
}

/**
 * Receipt line the UI shows. Success is only claimed from a sealed receipt; a terminal
 * run without one is reported as unconfirmed, never inferred from the status field.
 */
export function outcomeLabel(view: RunViewDTO): {
  text: string;
  tone: "ok" | "warn" | "error" | "muted";
} {
  const { receipt, run } = view;
  if (receipt) {
    const evidence = `${receipt.verifiedEvidenceCount}/${receipt.evidenceCount} evidence verified`;
    if (receipt.status === "success")
      return { text: `Receipt sealed: success · ${evidence}`, tone: "ok" };
    return { text: `Receipt sealed: ${receipt.status} · ${evidence}`, tone: "error" };
  }
  if (run.terminal) return { text: `Run ${run.status}; no receipt sealed yet`, tone: "warn" };
  return { text: `Run ${run.status}`, tone: "muted" };
}
