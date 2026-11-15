from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404

from accounts.models import User
from audit.models import AuditEvent
from clients.models import Client

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


def create_case(form, actor):
    client = form.cleaned_data["client"]
    attorney = form.cleaned_data["responsible_attorney"]
    client = lock_visible_client(actor, client.pk, active_only=True)
    case = form.save(commit=False)
    case.number = f"CASE-{uuid4().hex}"
    case.responsible_attorney = attorney
    case.created_by = actor
    case.save()
    CaseClient.objects.create(case=case, client=client)
    CaseMembership.objects.create(
        case=case, user=attorney, responsibility=CaseMembership.Responsibility.LEAD
    )
    if actor.pk != attorney.pk:
        CaseMembership.objects.create(
            case=case,
            user=actor,
            responsibility=(
                CaseMembership.Responsibility.ATTORNEY
                if actor.role == User.Role.ATTORNEY
                else CaseMembership.Responsibility.SUPPORT
            ),
        )
    return case


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
