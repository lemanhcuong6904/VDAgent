"""The invocation runtime: scheduling stacks, running agent turns, routing agent calls.

Named invariants it upholds:

- **Stack lock**: one running invocation per (user, agent); only its run task writes that stack.
- **Stack integrity**: every assistant tool call in a stack has a tool result, synthesised on
  failure, cancel or restart.
- **Acyclic wait graph**: a call that would close a cycle of waiting agents is rejected.
- **User isolation**: a run reads and writes only its own user's data.

May import: `core`, `config`, `conversations`, `memory`, `plugins`.
"""

from vdagent_backend.runtime.context import RUN_OUTCOMES
from vdagent_backend.runtime.engine import (
    Engine,
    IdempotencyConflictError,
    InterruptedHook,
    TaskFinishedError,
    TaskNotFoundError,
    UnknownAgentError,
)

__all__ = [
    "RUN_OUTCOMES",
    "Engine",
    "IdempotencyConflictError",
    "InterruptedHook",
    "TaskFinishedError",
    "TaskNotFoundError",
    "UnknownAgentError",
]
