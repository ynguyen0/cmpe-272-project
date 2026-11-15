from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404

from accounts.models import User
from audit.models import AuditEvent
from clients.models import Client

from .models import Case, CaseClient, CaseMembership
from .policies import case_allows, cases_visible_to, clients_visible_to


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


def create_case(form, actor):
    client = form.cleaned_data["client"]
    attorney = form.cleaned_data["responsible_attorney"]
    Client.objects.select_for_update(no_key=True).get(pk=client.pk)
    if not clients_visible_to(actor).filter(pk=client.pk, status=Client.Status.ACTIVE).exists():
        raise Http404
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
    AuditEvent.objects.create(
        actor=request.user,
        action=action,
        resource_type=record._meta.model_name,
        resource_id=str(record.pk),
        result=AuditEvent.Result.SUCCESS,
        correlation_id=uuid4(),
        # Audit change names are limited by the existing append-only schema.
        changed_fields=[field for field in fields if field in AuditEvent.CHANGE_FIELDS],
    )
