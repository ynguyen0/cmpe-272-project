"""Role capabilities and record scopes for confidential application data."""

from enum import StrEnum

from django.db.models import Q

from accounts.models import User
from audit.models import AuditEvent
from clients.models import Client
from documents.models import Document
from work.models import Deadline, Task

from .models import Case, CaseMembership

Role = User.Role


class Action(StrEnum):
    MANAGE_ACCOUNTS = "manage_accounts"
    CREATE_RECORDS = "create_case_records"
    VIEW_CASE = "view_case"
    EDIT_CASE = "edit_case"
    MANAGE_DOCUMENTS = "manage_case_documents"
    ASSIGN_TASKS = "assign_case_tasks"
    COMPLETE_TASK = "complete_task"
    ARCHIVE_CASE = "archive_case"
    VIEW_AUDIT = "view_organization_audit"


ALL_ROLES = frozenset(Role)
ROLE_RULES = {
    Action.MANAGE_ACCOUNTS: ({Role.ADMINISTRATOR}, set()),
    Action.CREATE_RECORDS: ({Role.ADMINISTRATOR, Role.ATTORNEY}, {Role.STAFF}),
    Action.VIEW_CASE: (ALL_ROLES, set()),
    Action.EDIT_CASE: (ALL_ROLES, set()),
    Action.MANAGE_DOCUMENTS: ({Role.ADMINISTRATOR, Role.ATTORNEY}, {Role.STAFF}),
    Action.ASSIGN_TASKS: ({Role.ADMINISTRATOR, Role.ATTORNEY}, {Role.STAFF}),
    Action.COMPLETE_TASK: (ALL_ROLES, set()),
    Action.ARCHIVE_CASE: ({Role.ATTORNEY}, {Role.ADMINISTRATOR}),
    Action.VIEW_AUDIT: (set(), {Role.ADMINISTRATOR}),
}


def has_capability(user, action):
    if not user.is_authenticated or not user.is_active or action not in ROLE_RULES:
        return False
    allowed_roles, grant_roles = ROLE_RULES[action]
    # Require a direct grant. Django's has_perm also grants every permission to superusers.
    return user.role in allowed_roles or (
        user.role in grant_roles
        and user.user_permissions.filter(
            content_type__app_label="cases", content_type__model="case", codename=action
        ).exists()
    )


def cases_visible_to(user):
    if not has_capability(user, Action.VIEW_CASE):
        return Case.objects.none()
    memberships = CaseMembership.objects.filter(user=user, is_active=True)
    return Case.objects.filter(pk__in=memberships.values("case_id"))


def clients_visible_to(user):
    if not has_capability(user, Action.VIEW_CASE):
        return Client.objects.none()
    return Client.objects.filter(
        Q(case_links__case__in=cases_visible_to(user), case_links__is_active=True)
        | Q(case_links__isnull=True, created_by=user)
    ).distinct()


def documents_visible_to(user):
    return Document.objects.filter(case__in=cases_visible_to(user))


def tasks_visible_to(user):
    return Task.objects.filter(case__in=cases_visible_to(user))


def deadlines_visible_to(user):
    return Deadline.objects.filter(case__in=cases_visible_to(user))


def audit_events_visible_to(user):
    if has_capability(user, Action.VIEW_AUDIT):
        return AuditEvent.objects.all()
    return AuditEvent.objects.none()


def eligible_assignees(case):
    return User.objects.filter(
        is_active=True, role__in=ALL_ROLES, memberships__case=case, memberships__is_active=True
    ).order_by("full_name", "pk")


def case_allows(user, action, case):
    if not has_capability(user, action) or not cases_visible_to(user).filter(pk=case.pk).exists():
        return False
    if action == Action.VIEW_CASE:
        return True
    if action == Action.ARCHIVE_CASE:
        return user.role == Role.ADMINISTRATOR or case.responsible_attorney_id == user.pk
    return action in {
        Action.EDIT_CASE,
        Action.MANAGE_DOCUMENTS,
        Action.ASSIGN_TASKS,
        Action.COMPLETE_TASK,
    }


def editable_case_fields(user, case):
    if not case_allows(user, Action.EDIT_CASE, case):
        return ()
    if user.role == Role.STAFF:
        return ("summary", "court_docket_number")
    return ("title", "type", "summary", "court_docket_number")


def can_complete_task(user, task):
    return task.assignee_id == user.pk and case_allows(user, Action.COMPLETE_TASK, task.case)
