"""Stack compaction: fold a stack's finished, other-task messages into its summary before a turn.

Compaction never fails a turn: a timeout, an exception or a non-string summary is logged and the
turn continues with the uncompacted history.
"""

from __future__ import annotations

import asyncio
import logging

from vdagent_sdk import Agent

from vdagent_backend.conversations import Messages
from vdagent_backend.core import describe
from vdagent_backend.runtime.history import to_message
from vdagent_backend.runtime.run import Run

log = logging.getLogger(__name__)

COMPACT_TIMEOUT_S = 150.0  # plugin model timeout (120 s) plus margin


async def compact(run: Run, agent: Agent, messages: Messages, timeout_s: float) -> None:
    """Summarise the uncompacted messages of finished tasks other than `run`'s on its stack.

    The summarising call is `run.rpc` while it runs, so a task cancel can cancel it.
    """
    rows = await messages.compaction_candidates(run.user_id, run.agent, run.task_id)
    if not rows:
        return
    previous = await messages.get_summary(run.user_id, run.agent) or ""
    compaction = asyncio.ensure_future(asyncio.wait_for(agent.compact(previous, [to_message(r) for r in rows]), timeout_s))
    run.rpc = compaction
    try:
        summary = await compaction
    except asyncio.CancelledError:
        raise
    except Exception as e:
        reason = f"no summary within {timeout_s:g}s" if isinstance(e, TimeoutError) else describe(e)
        log.warning("compaction of stack (%s, %s) failed, continuing: %s", run.user_id, run.agent, reason)
        return
    finally:
        run.rpc = None
    if not isinstance(summary, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        log.warning(
            "compaction of stack (%s, %s) returned %s, not str; continuing", run.user_id, run.agent, type(summary).__name__
        )
        return
    await messages.apply_compaction(run.user_id, run.agent, summary, [r["id"] for r in rows])
