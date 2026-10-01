import { splitAgentReport } from "../../ui/agentReport";
import { MarkdownText } from "../Markdown";
import { AgentReportCard } from "./AgentReportCard";

/** Show a human-readable AgentReport answer; keep the JSON contract inside its collapsed details. */
export function MessageText({ text, className }: { text: string; className?: string }) {
  const segments = splitAgentReport(text);
  if (!segments.some((s) => s.kind === "report")) return <MarkdownText text={text} className={className} />;
  const report = segments.find((s) => s.kind === "report");
  const summary = report?.kind === "report" ? report.report.summary.trim() : "";
  return (
    <div className={className}>
      {segments.map((s, i) =>
        s.kind === "markdown" && s.text.trim() !== summary ? (
          <MarkdownText key={i} text={s.text} />
        ) : s.kind === "report" ? (
          <AgentReportCard key={i} report={s.report} raw={s.raw} />
        ) : null,
      )}
    </div>
  );
}
