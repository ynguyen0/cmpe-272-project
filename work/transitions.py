"""Allowed status moves for tasks and deadlines (TASK-03, DATE-02).

Keeping the maps here, rather than inside a form or a view, means the same rule
governs every caller: the form only offers reachable choices, and the service
checks the move again before writing. A status not listed as a destination is
rejected, which is what makes an unknown or skipped transition fail rather than
silently succeed.
"""

from .models import Deadline, Task

#: Task moves. `Done` reopens only to `To do`, never straight back to progress.
TASK_TRANSITIONS = {
    Task.Status.TODO: {Task.Status.IN_PROGRESS, Task.Status.DONE},
    Task.Status.IN_PROGRESS: {Task.Status.TODO, Task.Status.DONE},
    Task.Status.DONE: {Task.Status.TODO},
}

#: Deadline moves. Resolution is explicit in both directions.
DEADLINE_TRANSITIONS = {
    Deadline.Status.PENDING: {Deadline.Status.COMPLETED, Deadline.Status.CANCELLED},
    Deadline.Status.COMPLETED: {Deadline.Status.PENDING},
    Deadline.Status.CANCELLED: {Deadline.Status.PENDING},
}


def allows(transitions, current, target):
    """True when ``current -> target`` is permitted. Unknown values are refused."""
    return target in transitions.get(current, set())
