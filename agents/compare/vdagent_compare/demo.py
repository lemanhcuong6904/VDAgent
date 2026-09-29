"""Terminal demo of the Compare agent — the same agent the Backend loads, without the UI.

  uv run python -m vdagent_compare.demo --question "Tại sao A12-08 bán chậm?"
  uv run python -m vdagent_compare.demo --chat                 # ask several questions in a row
  uv run python -m vdagent_compare.demo --question "..." --json   # raw artifacts, engine only

With `OPENAI_API_KEY` in agents/compare/.env the model plans and words answers (spec §1.9);
`--no-llm` (or no key) uses rules and templates. Numbers always come from the engine.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from vdagent_sdk import ToolCall

from .agent import CompareAgent
from .vh_chat import HELP, parse_request
from .vh_service import CompareService

EXIT_WORDS = {"thoat", "thoát", "exit", "quit", "q"}


def to_terminal(text: str) -> str:
    """Markdown (headings, bold, italics, pipe tables) → plain text with aligned table columns."""
    out: list[str] = []
    table: list[list[str]] = []

    def flush() -> None:
        if not table:
            return
        widths = [max(len(row[i]) for row in table if i < len(row)) for i in range(len(table[0]))]
        for n, row in enumerate(table):
            out.append("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
            if n == 0:
                out.append("  " + "  ".join("-" * w for w in widths))
        table.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                table.append([re.sub(r"\*\*|__", "", cell) for cell in cells])
            continue
        flush()
        if stripped.startswith("#"):
            line = stripped.lstrip("#").strip().upper()
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", line)
        out.append(line)
    flush()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


@dataclass
class _Ctx:
    """The slice of `InvocationContext` the Compare agent uses."""

    history: list[dict[str, Any]]
    max_steps: int = 12
    answer: str = ""
    evidence: list[str] = field(default_factory=list)

    async def emit_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        if not tool_calls:
            self.answer = content

    async def emit_tool_result(self, tool_call_id: str, content: str) -> None:
        self.evidence.append(content)


def _agent(use_llm: bool) -> CompareAgent:
    llm = None
    if use_llm:
        from .llm import LiteLLMJsonClient
        from .settings import load_llm_settings, read_env

        settings = load_llm_settings(read_env())
        if settings is not None:
            llm = LiteLLMJsonClient(models=settings.models, api_base=settings.openai_base_url,
                                    api_key=settings.openai_api_key, timeout_s=settings.llm_timeout_s)
    return CompareAgent(llm=llm)


def _ask(agent: CompareAgent, history: list[dict[str, Any]], question: str) -> str:
    history.append({"role": "user", "content": f"[from: user] {question}"})
    ctx = _Ctx(history=list(history))
    asyncio.run(agent.invoke(ctx))
    history.append({"role": "assistant", "content": ctx.answer})
    return ctx.answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare Agent — demo trên terminal")
    parser.add_argument("--question", help="một câu hỏi (mặc định: câu hero A12-08)")
    parser.add_argument("--chat", action="store_true", help="hỏi liên tục; gõ 'thoát' để dừng")
    parser.add_argument("--no-llm", action="store_true", help="không gọi mô hình, chỉ quy tắc + câu mẫu")
    parser.add_argument("--markdown", action="store_true", help="in nguyên markdown (mặc định: chữ thường)")
    parser.add_argument("--request-file", type=Path, help="JSON Compare request; in artifact gốc")
    parser.add_argument("--json", action="store_true", help="in artifact gốc (JSON), chỉ engine")
    parser.add_argument("--artifact-out", type=Path, help="ghi artifact gốc ra file")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    show = (lambda text: text) if args.markdown else to_terminal

    if args.json or args.request_file or args.artifact_out:
        request = (json.loads(args.request_file.read_text(encoding="utf-8")) if args.request_file
                   else parse_request(args.question or "Tại sao A12-08 bán chậm?"))
        if not isinstance(request, dict):
            parser.error(HELP)
        result = CompareService().run(request)
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.artifact_out:
            args.artifact_out.parent.mkdir(parents=True, exist_ok=True)
            args.artifact_out.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0

    agent = _agent(use_llm=not args.no_llm)
    mode = "mô hình " + ", ".join(agent.model_names) if agent.has_model else "quy tắc + câu mẫu (không dùng mô hình)"
    history: list[dict[str, Any]] = []
    if not args.chat:
        print(show(_ask(agent, history, args.question or "Tại sao A12-08 bán chậm?")))
        return 0
    print(f"Compare Agent · {mode}. Gõ câu hỏi, 'thoát' để dừng.\n{HELP}\n")
    while True:
        try:
            question = input("Bạn > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in EXIT_WORDS:
            break
        if question:
            print("\nCompare > " + show(_ask(agent, history, question)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
