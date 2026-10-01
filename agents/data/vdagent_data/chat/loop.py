"""The LLM loop of the explanation chat: tools in, a checked answer out.

The model may call the read-only tools of `tools.py` for up to `MAX_ROUNDS` rounds (the last round offers none). Its final
answer is accepted only when every number and identifier in it occurs in what the tools returned or in the conversation
(`narrate.unsupported_figures` names the ones that do not); otherwise it is asked once to rewrite, then replaced by a plain refusal. Nothing the model says
reaches the user unchecked, and nothing here touches the warehouse or writes an artifact.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from vdagent_sdk import ToolCall

from vdagent_data.chat.packages import load_latest
from vdagent_data.chat.tools import ChatTools
from vdagent_data.llm import LLMClient, LLMTimeoutError
from vdagent_data.narrate import StepSink, unsupported_figures
from vdagent_data.steps import Tools

log = logging.getLogger(__name__)

MAX_ROUNDS = 5
MAX_NAMED = 8  # unsupported values named in the log and in the request to rewrite
MAX_TURNS = 12  # messages of the conversation shown to the model
SHOWN_CHARS = 1_500  # a tool result as the person watching sees it (the model gets all of it)

NO_PACKAGES_TEXT = ("Mình chưa có dữ liệu nào để giải thích. Hãy chạy một phân tích trước (ví dụ hỏi Orchestrator về một căn); "
                    "khi Data lấy xong, bạn quay lại đây hỏi mình nhé.")
UNGROUNDED_TEXT = ("Mình chưa thể trả lời câu này một cách chắc chắn từ dữ liệu đã lấy, và mình không muốn nói số liệu không có trong đó. "
                   "Bạn thử hỏi cụ thể hơn, ví dụ về một căn, một chỉ số hoặc một giá trị còn thiếu.")
STEP_LIMIT_TEXT = "Mình tra dữ liệu nhiều bước mà vẫn chưa ra câu trả lời. Bạn thử hỏi gọn hơn nhé."
TIMEOUT_TEXT = "Mình trả lời hơi lâu nên chưa kịp xong. Bạn hỏi lại giúp mình nhé."
CORRECTION = ("Câu trả lời có số hoặc mã không nằm trong kết quả tra cứu hay trong cuộc trò chuyện. "
              "Hãy viết lại chỉ dùng số và mã có trong kết quả tool; nếu thiếu thông tin thì nói rõ là chưa có.")

_FROM = re.compile(r"^\[from: ([^\]]+)\]\s*")
_LIST_MARKER = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+")  # "1. " at the start of a line numbers a list; it is not a figure


def chat_turns(history: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The user's questions and the chat's own answers, as plain turns, newest `MAX_TURNS` at most, the first one a question.

    Messages of the pipeline (an agent's request, the narrated steps, the JSON report) and the tool traffic of earlier
    chat turns are dropped: the model gets its facts from the tools, not from replayed history.
    """
    turns: list[dict[str, str]] = []
    in_chat = False
    for message in history:
        content = str(message.get("content") or "")
        if message.get("role") == "user":
            match = _FROM.match(content)
            body = content[match.end():] if match else content
            in_chat = match.group(1) == "user" if match else True
            if in_chat:
                turns.append({"role": "user", "content": body.strip()})
        elif message.get("role") == "assistant" and in_chat and content.strip() and not message.get("tool_calls"):
            turns.append({"role": "assistant", "content": content.strip()})
    turns = turns[-MAX_TURNS:]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


def _shown(result: str) -> str:
    return result if len(result) <= SHOWN_CHARS else result[:SHOWN_CHARS] + "…"


class ChatLoop:
    def __init__(self, llm: LLMClient, *, system_prompt: str) -> None:
        self._llm, self._system_prompt = llm, system_prompt

    async def reply(self, history: Sequence[Mapping[str, Any]], tools: Tools, sink: StepSink) -> str:
        """The answer to the last question of `history`. Intermediate tool calls are shown through `sink`."""
        packages = await load_latest(tools)
        if packages is None:
            return NO_PACKAGES_TEXT
        chat_tools = ChatTools(packages)
        turns = chat_turns(history)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system_prompt}, *turns]
        known = [t["content"] for t in turns]  # what an answer may repeat: the conversation and every tool result
        corrected = False
        for round_no in range(1, MAX_ROUNDS + 1):
            last = round_no == MAX_ROUNDS
            try:
                reply = await self._llm.complete(messages, chat_tools.schemas(), "none" if last else "auto")
            except LLMTimeoutError:
                return TIMEOUT_TEXT
            if reply.tool_calls and not last:
                results = [(call, self._run(chat_tools, call)) for call in reply.tool_calls]
                await sink.step(reply.content, [(call, _shown(result)) for call, result in results])
                messages.append(reply.to_openai())
                for call, result in results:
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
                    known.append(result)
                continue
            text = reply.content.strip()
            if not text:
                return STEP_LIMIT_TEXT
            unsupported = unsupported_figures(_LIST_MARKER.sub("", text), known)
            if not unsupported:
                return text
            log.info("data chat: answer rejected, no source for %s: %s", unsupported[:MAX_NAMED], text[:300])
            if corrected or last:
                return UNGROUNDED_TEXT
            corrected = True
            named = ", ".join(unsupported[:MAX_NAMED])
            messages += [{"role": "assistant", "content": text}, {"role": "user", "content": f"{CORRECTION} Chưa có trong kết quả: {named}."}]
        return STEP_LIMIT_TEXT

    @staticmethod
    def _run(chat_tools: ChatTools, call: ToolCall) -> str:
        try:
            args = json.loads(call.arguments_json) if call.arguments_json.strip() else {}
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"arguments are not valid JSON: {exc}"})
        if not isinstance(args, dict):
            return json.dumps({"error": "arguments must be a JSON object"})
        return json.dumps(chat_tools.run(call.name, args), ensure_ascii=False, default=str)
