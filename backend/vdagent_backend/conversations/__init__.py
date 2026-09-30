"""Conversations: users, tasks, invocations, per-(user, agent) message stacks, and their API shapes.

Every read of user data filters on the owning user where the caller supplies one (user isolation).

May import: `core`, `persistence`.
"""

from vdagent_backend.conversations.dto import invocation_dto, message_dto, task_dto, user_dto
from vdagent_backend.conversations.messages import Messages
from vdagent_backend.conversations.tasks import TASK_STATUSES, Tasks
from vdagent_backend.conversations.users import Users

__all__ = [
    "TASK_STATUSES",
    "Messages",
    "Tasks",
    "Users",
    "invocation_dto",
    "message_dto",
    "task_dto",
    "user_dto",
]
