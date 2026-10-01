from __future__ import annotations

from pydantic import ValidationError
from vdagent_agentkit.mcp_client import JsonTools, McpSessionFactory, open_mcp_session
from vdagent_contracts.messages import ContractMessage, StepSpec, parse_incoming
from vdagent_contracts.reports import AgentReport, ReportError, render_agent_report
from vdagent_sdk import InvocationContext, Message

from .fixtures import load_demo_task
from .fixture_store import FixtureArtifactStore
from .mock_upstream import MockUpstreamEvent, MockUpstreamReasoner, run_mock_upstream_pipeline
from .runtime import canonical_input_hash
from .service import ChartAgentService
from .stepspec import run_step as run_stepspec

NAME = "chart"
DESCRIPTION = (
    "Builds validated, traceable chart specifications. A StepSpec@1 draw_chart request reads pinned insight /"
    " comparison artifacts and returns chart_spec artifacts in an AgentReport@1."
)
DEMO_DISABLED_TEXT = (
    "Chart demo mode is disabled in this deployment (demo/synthetic data never enters production, D6). Send a"
    " StepSpec@1 draw_chart request with pinned insight/comparison artifacts, or enable CHART_DEMO=on locally."
)


class ChartPluginAgent:
    def __init__(
        self,
        service: ChartAgentService,
        *,
        upstream_reasoner: MockUpstreamReasoner | None = None,
        demo_enabled: bool = True,
        mcp_session_factory: McpSessionFactory = open_mcp_session,
    ) -> None:
        self._service = service
        self._upstream_reasoner = upstream_reasoner
        self.demo_enabled = demo_enabled
        self._mcp_session_factory = mcp_session_factory

    async def _contract(self, ctx: InvocationContext, message: ContractMessage) -> None:
        """StepSpec@1 (WS4): pinned insight/comparison artifacts through MCP → chart_spec artifacts → AgentReport@1."""
        if message.contract != "StepSpec@1":
            text = f"chart accepts StepSpec@1, not {message.contract}"
            report = AgentReport(state="rejected", summary=text, error=ReportError(code="UNSUPPORTED_CONTRACT", message=text))
        else:
            try:
                step = StepSpec.model_validate(message.data)
            except ValidationError as exc:
                report = AgentReport(state="rejected", summary="invalid StepSpec@1",
                                     error=ReportError(code="INVALID_STEPSPEC", message=f"{exc.error_count()} error(s)"))
            else:
                async with self._mcp_session_factory(ctx.mcp.url, ctx.mcp.token) as mcp:
                    report = await run_stepspec(step, JsonTools(mcp), reasoner=self._upstream_reasoner)
        head = f"Chart: {report.state}" + (f" ({report.error.code})" if report.error else "")
        await ctx.emit_assistant(render_agent_report(head, report))

    async def invoke(self, ctx: InvocationContext) -> None:
        text = str(ctx.history[-1].get("content", "")).strip()
        try:
            incoming = parse_incoming(text)
        except ValueError:
            incoming = None
        if isinstance(incoming, ContractMessage):
            await self._contract(ctx, incoming)
            return
        if text.startswith("[from:") and "] " in text:
            text = text.split("] ", 1)[1]
        if not self.demo_enabled:
            await ctx.emit_assistant(DEMO_DISABLED_TEXT)
            return
        prefix = ""
        if text.startswith("chart demo "):
            scenario = text.removeprefix("chart demo ").strip()
            try:
                task = load_demo_task(scenario)
                service = self._service
                result = await service.execute_async(task)
            except KeyError:
                await ctx.emit_assistant(f"Unknown chart demo scenario: {scenario}")
                return
        elif text.startswith("chart ask "):
            question = text.removeprefix("chart ask ").strip()
            if not question:
                await ctx.emit_assistant("Use `chart ask <natural language question>`.")
                return
            async def emit_upstream(event: MockUpstreamEvent) -> None:
                await ctx.emit_assistant(event.to_message())

            bundle = await run_mock_upstream_pipeline(question, emit_upstream, reasoner=self._upstream_reasoner)
            task = bundle.task
            service = ChartAgentService(FixtureArtifactStore(bundle.artifacts))
            await ctx.emit_assistant("Chart Agent running: validating upstream artifacts and rendering ChartSpec")
            result = service.execute(task, bundle.llm_suggestions)
            prefix = f"{bundle.summary} "
        else:
            await ctx.emit_assistant("Use `chart demo <scenario>` or `chart ask <natural language question>`.")
            return
        if result.chart_artifacts:
            refs = await _persist_chart_refs(ctx, service, task, result.chart_artifacts)
            await ctx.emit_assistant(prefix + "Created chart artifact: " + ", ".join(refs))
        elif result.dependency_requests:
            request = result.dependency_requests[0]
            await ctx.emit_assistant(f"Chart could not run: required artifact {request['artifact_id']}@{request['version']} is unavailable.")
        else:
            await ctx.emit_assistant("Chart task failed validation.")

    async def compact(self, previous_summary: str, messages: list[Message]) -> str:
        return previous_summary


async def _persist_chart_refs(
    ctx: InvocationContext,
    service: ChartAgentService,
    task,
    chart_refs: tuple[str, ...],
) -> list[str]:
    refs = list(chart_refs)
    store = getattr(ctx, "artifacts", None)
    if store is None:
        return refs
    refs = []
    for local_ref in chart_refs:
        local = service.artifacts[local_ref.removesuffix("@1")]
        persisted_spec = {**local["semantic_spec"], **local["render_spec"]}
        lineage = {"input_artifact_refs": local["lineage"]}
        validation = dict(local["semantic_spec"].get("validation", {"overall_result": "pass"}))
        limitations = list(local.get("limitations", ()))
        content_key = canonical_input_hash(
            {
                "chart_spec": persisted_spec,
                "dataset_hash": local["dataset"]["dataset_hash"],
                "title": local["presentation"]["title"],
                "lineage": lineage,
                "validation": validation,
                "limitations": limitations,
            }
        )
        saved = await store.save_chart_spec(
            title=local["presentation"]["title"],
            chart_spec=persisted_spec,
            idempotency_key=f"{task.idempotency_key}:{local_ref}:{content_key}",
            logical_chart_id=local["semantic_spec"]["chart_id"],
            dataset_hash=local["dataset"]["dataset_hash"],
            lineage=lineage,
            validation=validation,
            limitations=limitations,
        )
        refs.append(f"{saved['id']}@{saved['version']}")
    return refs
