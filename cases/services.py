from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clients.models import Client
from config.models import ConcurrentEditError
from work.models import Deadline, Task

from .models import Case, CaseClient, CaseMembership
from .policies import can_link_clients, case_allows, cases_visible_to, clients_visible_to


def lock_actor(request):
    if request.method == "POST":
        actor = User.objects.select_for_update(no_key=True).get(pk=request.user.pk)
        if (
            not actor.is_active
            or actor.get_session_auth_hash() != request.user.get_session_auth_hash()
        ):
            raise PermissionDenied
        request.user = actor
    return request.user


def case_for_action(request, pk, action):
    actor = lock_actor(request)
    cases = cases_visible_to(actor)
    if request.method == "POST":
        cases = cases.select_for_update(no_key=True)
    case = get_object_or_404(cases, pk=pk)
    if request.method == "POST":
        # Serialize writes with revocation of the membership that authorizes them.
        get_object_or_404(
            CaseMembership.objects.select_for_update(no_key=True),
            case=case,
            user=actor,
            is_active=True,
        )
    if not case_allows(actor, action, case):
        raise PermissionDenied
    return case


def require_editable(case):
    if case.status == Case.Status.CLOSED or case.is_archived:
        raise PermissionDenied


def lock_visible_client(actor, pk, *, active_only=False):
    # Lock the client before changing its status or any of its links.
    scoped = clients_visible_to(actor)
    clients = Client.objects.select_for_update(no_key=True).filter(pk__in=scoped.values("pk"))
    client = get_object_or_404(clients, pk=pk)
    if active_only and client.status != Client.Status.ACTIVE:
        raise Http404
    # Recheck using fresh reads after locking. A historical link rules out intake access.
    links = CaseClient.objects.filter(client=client)
    if client.created_by_id == actor.pk and not links.exists():
        return client
    link = (
        links.select_for_update(no_key=True)
        .filter(is_active=True, case__in=cases_visible_to(actor))
        .order_by("pk")
        .first()
    )
    if link is None:
        raise Http404
    get_object_or_404(
        CaseMembership.objects.select_for_update(no_key=True),
        case_id=link.case_id,
        user=actor,
        is_active=True,
    )
    return client


def link_client(case, client, actor):
    if not can_link_clients(actor, case):
        raise PermissionDenied
    require_editable(case)
    client = lock_visible_client(actor, client.pk, active_only=True)
    link, created = CaseClient.objects.get_or_create(case=case, client=client)
    if not created:
        if link.is_active:
            raise ValidationError("This client is already linked to the case.")
        link.update_with_revision(link.revision, is_active=True)
    return link


CASE_TRANSITIONS = {
    Case.Status.OPEN: (Case.Status.IN_PROGRESS, Case.Status.ON_HOLD, Case.Status.CLOSED),
    Case.Status.IN_PROGRESS: (Case.Status.ON_HOLD, Case.Status.CLOSED),
    Case.Status.ON_HOLD: (Case.Status.IN_PROGRESS, Case.Status.OPEN, Case.Status.CLOSED),
    Case.Status.CLOSED: (Case.Status.OPEN,),
}


def lock_team_accounts(user_ids):
    # Another workflow may already hold an account lock while waiting on this case.
    # Fail with a reload prompt instead of waiting while holding case and actor locks.
    try:
        with transaction.atomic():
            users = (
                User.objects.filter(pk__in=user_ids)
                .order_by("pk")
                .select_for_update(no_key=True, nowait=True)
            )
            return {user.pk: user for user in users}
    except OperationalError as exc:
        if getattr(exc.__cause__, "sqlstate", None) != "55P03":
            raise
        raise ConcurrentEditError("A team account is being updated. Reload and try again.") from exc


def require_team_role(users, pk, role):
    account = users.get(pk)
    if account is None or not account.is_active or account.role != role:
        raise ConcurrentEditError("A selected account is no longer eligible. Reload the form.")


def create_case(form, actor):
    data = form.cleaned_data
    client_ids = {data["client"].pk, *(client.pk for client in data["additional_clients"])}
    attorney_id = data["responsible_attorney"].pk
    staff_ids = {staff.pk for staff in data["assigned_staff"]}
    users = lock_team_accounts({attorney_id, *staff_ids})
    require_team_role(users, attorney_id, User.Role.ATTORNEY)
    for pk in staff_ids:
        require_team_role(users, pk, User.Role.STAFF)
    for pk in sorted(client_ids):
        lock_visible_client(actor, pk, active_only=True)

    case = form.save(commit=False)
    case.number = f"CASE-{uuid4().hex}"
    case.responsible_attorney_id = attorney_id
    case.created_by = actor
    case.save()
    CaseClient.objects.bulk_create(CaseClient(case=case, client_id=pk) for pk in client_ids)
    responsibilities = dict.fromkeys(staff_ids, CaseMembership.Responsibility.SUPPORT)
    responsibilities[actor.pk] = (
        CaseMembership.Responsibility.ATTORNEY
        if actor.role == User.Role.ATTORNEY
        else CaseMembership.Responsibility.SUPPORT
    )
    responsibilities[attorney_id] = CaseMembership.Responsibility.LEAD
    CaseMembership.objects.bulk_create(
        CaseMembership(case=case, user_id=pk, responsibility=responsibility)
        for pk, responsibility in responsibilities.items()
    )
    return case


def set_membership(case, memberships, pk, responsibility, *, is_active=True):
    member = memberships.get(pk)
    if member is None:
        CaseMembership.objects.create(
            case=case, user_id=pk, responsibility=responsibility, is_active=is_active
        )
        return True
    if member.responsibility != responsibility or member.is_active != is_active:
        member.update_with_revision(
            member.revision, responsibility=responsibility, is_active=is_active
        )
        return True
    return False


def set_responsible_attorney(case, memberships, users, attorney_id):
    old = case.responsible_attorney_id
    if old != attorney_id:
        responsibility = (
            CaseMembership.Responsibility.ATTORNEY
            if users[old].role == User.Role.ATTORNEY
            else CaseMembership.Responsibility.SUPPORT
        )
        set_membership(case, memberships, old, responsibility, is_active=memberships[old].is_active)
    return set_membership(case, memberships, attorney_id, CaseMembership.Responsibility.LEAD)


def outstanding_work(case):
    return (
        case.tasks.exclude(status=Task.Status.DONE).order_by("due_at", "pk"),
        case.deadlines.filter(status=Deadline.Status.PENDING).order_by("due_at", "pk"),
    )


@transaction.atomic
def update_case_team(case, data):
    attorney_id = data["responsible_attorney"].pk
    staff_ids = {user.pk for user in data["assigned_staff"]}
    memberships = {member.user_id: member for member in case.memberships.all()}
    users = lock_team_accounts({*memberships, attorney_id, *staff_ids})
    require_team_role(users, attorney_id, User.Role.ATTORNEY)
    for pk in staff_ids:
        require_team_role(users, pk, User.Role.STAFF)
    removed = {
        pk
        for pk, member in memberships.items()
        if member.is_active and users[pk].role == User.Role.STAFF and pk not in staff_ids
    }
    tasks, deadlines = outstanding_work(case)
    if (
        tasks.filter(assignee_id__in=removed).exists()
        or deadlines.filter(responsible_user_id__in=removed).exists()
    ):
        raise ValidationError(
            "Reassign unfinished tasks and pending deadlines before removing their team members."
        )

    changed = set_responsible_attorney(case, memberships, users, attorney_id)
    for pk in staff_ids:
        changed |= set_membership(case, memberships, pk, CaseMembership.Responsibility.SUPPORT)
    for pk in removed:
        changed |= set_membership(
            case, memberships, pk, CaseMembership.Responsibility.SUPPORT, is_active=False
        )
    fields = ["members"] if changed else []
    if attorney_id != case.responsible_attorney_id:
        fields.append("responsible_attorney")
    if fields:
        case.update_with_revision(data["revision"], responsible_attorney=attorney_id)
    return fields


@transaction.atomic
def change_case_status(case, data):
    status = data["status"]
    if case.is_archived or status not in CASE_TRANSITIONS[case.status]:
        raise ValidationError("This status transition is unavailable.")
    changes = {"status": status}
    if status == Case.Status.CLOSED:
        today = timezone.localdate()
        if case.opened_on > today:
            raise ValidationError("The case cannot close before its opened date.")
        changes["closed_on"] = today
    if case.status == Case.Status.CLOSED:
        changes["closed_on"] = None
        replacement = data.get("responsible_attorney")
        attorney_id = replacement.pk if replacement else case.responsible_attorney_id
        users = lock_team_accounts({case.responsible_attorney_id, attorney_id})
        require_team_role(users, attorney_id, User.Role.ATTORNEY)
        memberships = {member.user_id: member for member in case.memberships.all()}
        if not replacement and not memberships[attorney_id].is_active:
            raise ConcurrentEditError("Choose an active responsible attorney before reopening.")
        if set_responsible_attorney(case, memberships, users, attorney_id):
            changes["responsible_attorney"] = attorney_id
    case.update_with_revision(data["revision"], **changes)
    fields = list(changes)
    if "responsible_attorney" in changes:
        fields.append("members")
    return fields


def audit_change(request, action, record, fields=()):
    return audit_event(request, action, record._meta.model_name, str(record.pk), fields)


def audit_event(request, action, resource_type, resource_id="", fields=()):
    return AuditEvent.objects.create(
        actor=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=AuditEvent.Result.SUCCESS,
        correlation_id=uuid4(),
        # Audit change names are limited by the existing append-only schema.
        changed_fields=[field for field in fields if field in AuditEvent.CHANGE_FIELDS],
    )
