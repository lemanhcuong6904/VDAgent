import { splitAgentReport } from "../../ui/agentReport";
import { MarkdownText } from "../Markdown";
import { AgentReportCard } from "./AgentReportCard";

/** A message body: markdown, with an agent's `AgentReport@1` JSON fence shown as a card (the JSON stays in the card). */
export function MessageText({ text, className }: { text: string; className?: string }) {
  const segments = splitAgentReport(text);
  if (!segments.some((s) => s.kind === "report")) return <MarkdownText text={text} className={className} />;
  return (
    <div className={className}>
      {segments.map((s, i) =>
        s.kind === "markdown" ? (
          <MarkdownText key={i} text={s.text} />
        ) : (
          <AgentReportCard key={i} report={s.report} raw={s.raw} />
        ),
      )}
    </div>
  );
}
