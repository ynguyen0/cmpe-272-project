"""Personal dashboard and combined search (DASH-01, issue #17).

Every number here comes from the same access-filtered query as the list it links
to (`cases.worklists` and `cases.policies`), so a count can never include a
record the linked list would hide, and removing a membership removes the related
items on the next request.
"""

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse

from clients.models import Client
from clients.search import search_clients
from work.models import Deadline, Task

from .policies import (
    cases_visible_to,
    clients_visible_to,
    documents_visible_to,
    tasks_visible_to,
)
from .worklists import (
    open_cases,
    overdue_filter,
    pending_upcoming_deadlines,
    unfinished_tasks,
    unfinished_upcoming_tasks,
    visible_deadlines,
)

# Rows shown per dashboard card; the card links to the full, paginated list.
PREVIEW_ROWS = 5
SEARCH_PREVIEW_ROWS = 10
ACTIVITY_ROWS = 8


@dataclass
class Card:
    """One summary card: its count, a short preview and the matching list URL."""

    key: str
    title: str
    label: str
    count: int
    items: list
    url: str
    empty: str


def link(name, **params):
    url = reverse(name)
    return f"{url}?{urlencode(params)}" if params else url


def card(key, title, label, queryset, url, empty, *, related=()):
    preview = queryset.select_related(*related) if related else queryset
    return Card(key, title, label, queryset.count(), list(preview[:PREVIEW_ROWS]), url, empty)


def work_cards(user, now):
    cases = open_cases(user).order_by("number", "pk")
    tasks = unfinished_tasks(user)
    deadlines = visible_deadlines(user)
    by_due = ("due_at", "pk")
    me = str(user.pk)
    return [
        card(
            "cases",
            "My Open Cases",
            "Open Cases",
            cases.only("pk", "number", "title", "status"),
            link("cases:index", status="open"),
            "You Have No Open Cases.",
        ),
        card(
            "overdue_tasks",
            "My Overdue Tasks",
            "Overdue Tasks",
            overdue_filter(tasks, Task, now=now).order_by(*by_due),
            link("cases:work", assignee=me, window="overdue"),
            "No Overdue Tasks.",
            related=("case",),
        ),
        card(
            "upcoming_tasks",
            "My Tasks Due In The Next 7 Days",
            "Tasks Due Soon",
            unfinished_upcoming_tasks(tasks, now=now).order_by(*by_due),
            link("cases:work", assignee=me, window="upcoming"),
            "Nothing Due In The Next 7 Days.",
            related=("case",),
        ),
        card(
            "overdue_deadlines",
            "Overdue Deadlines",
            "Overdue Deadlines",
            overdue_filter(deadlines, Deadline, now=now).order_by(*by_due),
            link("cases:deadlines", window="overdue"),
            "No Overdue Deadlines.",
            related=("case",),
        ),
        card(
            "upcoming_deadlines",
            "Deadlines In The Next 7 Days",
            "Deadlines Due Soon",
            pending_upcoming_deadlines(deadlines, now=now).order_by(*by_due),
            link("cases:deadlines", window="upcoming"),
            "No Deadlines In The Next 7 Days.",
            related=("case",),
        ),
    ]


@dataclass
class Activity:
    when: datetime
    kind: str
    label: str
    case: object


def recent_activity(user):
    """Latest changes to records the user can open, newest first.

    Built from the records' own ``updated_at`` stamps rather than the audit log,
    which only administrators may read (LOG-01). Each source is limited before
    merging, so at most ``ACTIVITY_ROWS`` rows are loaded per record type.
    """
    cases = cases_visible_to(user).only("pk", "number", "title", "updated_at")

    def case_of(record):
        return record.case

    sources = [
        ("Case", cases, lambda c: c.title, lambda c: c),
        ("Task", tasks_visible_to(user).filter(is_archived=False), lambda t: t.title, case_of),
        ("Deadline", visible_deadlines(user), lambda d: d.title, case_of),
        ("Document", documents_visible_to(user), lambda d: d.title, case_of),
    ]
    rows = []
    for kind, queryset, label, case_of in sources:
        if kind != "Case":
            queryset = queryset.select_related("case").only(
                "pk", "title", "updated_at", "case__id", "case__number", "case__title"
            )
        for record in queryset.order_by("-updated_at", "-pk")[:ACTIVITY_ROWS]:
            rows.append(Activity(record.updated_at, kind, label(record), case_of(record)))
    rows.sort(key=lambda row: row.when, reverse=True)
    return rows[:ACTIVITY_ROWS]


def search_everything(user, query):
    """Cases and clients matching ``query``, with the same scope as their lists.

    Cases match on reference, title and court docket number; clients on name,
    ID, email and phone. Only names and references are returned, never contact
    details or notes, and each section links to its own paginated list.
    """
    cases = (
        cases_visible_to(user)
        .filter(is_archived=False)
        .filter(
            Q(number__icontains=query)
            | Q(title__icontains=query)
            | Q(court_docket_number__icontains=query)
        )
        .order_by("number", "pk")
        .only("pk", "number", "title", "status")
    )
    clients = search_clients(
        clients_visible_to(user).filter(status=Client.Status.ACTIVE), query
    ).order_by("name", "pk")
    return {
        "cases": Card(
            "cases",
            "Cases",
            "Cases",
            cases.count(),
            list(cases[:SEARCH_PREVIEW_ROWS]),
            link("cases:index", q=query),
            "No Matching Cases.",
        ),
        "clients": Card(
            "clients",
            "Clients",
            "Clients",
            clients.count(),
            list(clients.only("pk", "name", "type")[:SEARCH_PREVIEW_ROWS]),
            link("cases:clients", q=query),
            "No Matching Clients.",
        ),
    }
