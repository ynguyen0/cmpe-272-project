"""Shared work-list queries (TASK-03, DATE-02, DASH-01).

The dashboard and the task and deadline lists build their overdue and upcoming
windows from these functions, so a dashboard count always matches the list it
links to.
"""

from datetime import datetime, time, timedelta

from django.utils import timezone

from work.models import Deadline, Task

from .models import Case
from .policies import cases_visible_to, deadlines_visible_to, tasks_visible_to


def overdue_filter(queryset, model, now=None):
    """Unfinished work whose due instant has passed (TASK-03, DATE-02).

    Overdue is "due before now and not finished", so completed or cancelled work
    never counts however old it is.
    """
    finished = (
        [Task.Status.DONE]
        if model is Task
        else [Deadline.Status.COMPLETED, Deadline.Status.CANCELLED]
    )
    return queryset.filter(due_at__lt=now or timezone.now()).exclude(status__in=finished)


def upcoming_filter(queryset, now=None):
    """Pending work due from now through the end of firm-local day +7, inclusive.

    The window is computed in the firm timezone and then converted back, so the
    boundary lands on a real local midnight rather than a UTC one. That keeps the
    edge correct across daylight-saving changes.
    """
    now = now or timezone.now()
    firm_day = timezone.localtime(now).date() + timedelta(days=7)
    end = timezone.make_aware(datetime.combine(firm_day, time.max), timezone.get_default_timezone())
    return queryset.filter(due_at__gte=now, due_at__lte=end)


def open_cases(user):
    """Assigned cases that are neither closed nor archived."""
    return cases_visible_to(user).filter(is_archived=False).exclude(status=Case.Status.CLOSED)


def unfinished_tasks(user):
    """The user's own unfinished tasks in cases they can still see."""
    return (
        tasks_visible_to(user)
        .filter(is_archived=False, assignee=user)
        .exclude(status=Task.Status.DONE)
    )


def visible_deadlines(user):
    """Unarchived deadlines in the user's assigned cases."""
    return deadlines_visible_to(user).filter(is_archived=False)


def pending_upcoming_deadlines(queryset, now=None):
    return upcoming_filter(queryset.filter(status=Deadline.Status.PENDING), now=now)


def unfinished_upcoming_tasks(queryset, now=None):
    return upcoming_filter(queryset.exclude(status=Task.Status.DONE), now=now)
