from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from audit.models import AuditEvent
from cases.models import Case, CaseMembership
from work.models import Task

from .models import LoginThrottle, User
from .security import audit_account, lock_login_identity


def check_login(form):
    request = form.request
    # Clean the identity before hashing a password or creating a throttle record.
    try:
        email = form.fields["username"].clean(form.data.get("username"))
    except ValidationError:
        email = ""
    if email:
        email = email.lower()
        key = lock_login_identity(email)
        now = timezone.now()
        limit = LoginThrottle.objects.select_for_update().filter(pk=key).first()
        in_window = limit is not None and limit.expires_at > now
        if in_window and limit.failures >= settings.LOGIN_FAILURE_LIMIT:
            audit_account(request, "auth.login", AuditEvent.Result.DENIED)
            return "limited"
        # Password hash upgrades must not race with password changes or recovery.
        User.objects.select_for_update().filter(email=email).first()

    if form.is_valid():
        LoginThrottle.objects.filter(pk=key).delete()
        return "valid"

    if email and form.has_error("__all__", "invalid_login"):
        if in_window:
            limit.failures += 1
            limit.save(update_fields=["failures"])
        else:
            expired = (
                LoginThrottle.objects.select_for_update(skip_locked=True)
                .filter(expires_at__lte=now)
                .exclude(pk=key)
            )
            LoginThrottle.objects.filter(pk__in=expired.values("pk")).delete()
            LoginThrottle.objects.update_or_create(
                identity=key,
                defaults={
                    "failures": 1,
                    "expires_at": now + timedelta(seconds=settings.LOGIN_FAILURE_WINDOW),
                },
            )
    audit_account(request, "auth.login", AuditEvent.Result.FAILURE)
    return "invalid"


def require_administrator(request):
    if not request.user.is_administrator:
        audit_account(request, "account.admin", AuditEvent.Result.DENIED, actor=request.user)
        raise PermissionDenied


def lock_account_administration(request):
    # Every administration write takes the same transaction lock before checking roles.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [1279612998, 1])
    actor = User.objects.get(pk=request.user.pk)
    if not actor.is_administrator or not constant_time_compare(
        actor.get_session_auth_hash(), request.user.get_session_auth_hash()
    ):
        raise PermissionDenied
    request.user = actor


def check_assignments(target, *, role, is_active):
    if not is_active or role == User.Role.ADMINISTRATOR:
        if Task.objects.filter(assignee=target).exclude(status=Task.Status.DONE).exists():
            raise ValidationError("Reassign this account’s unfinished tasks before saving.")

    if (
        target.is_active
        and target.role == User.Role.ATTORNEY
        and (not is_active or role != User.Role.ATTORNEY)
    ):
        cases = Case.objects.exclude(status=Case.Status.CLOSED)
        if cases.filter(responsible_attorney=target).exists():
            raise ValidationError("Reassign this account’s active cases before saving.")
        other_memberships = CaseMembership.objects.filter(
            is_active=True, user__is_active=True, user__role=User.Role.ATTORNEY
        ).exclude(user=target)
        if (
            cases.filter(memberships__in=target.memberships.filter(is_active=True))
            .exclude(pk__in=other_memberships.values("case_id"))
            .exists()
        ):
            raise ValidationError("Assign another active attorney to this account’s cases first.")


def change_account_access(request, pk, *, role, is_active, revision):
    target = get_object_or_404(User.objects.select_for_update(), pk=pk)
    if target.revision != revision:
        raise ValidationError("This account has changed. Reload it before saving.")
    if target.is_administrator and (not is_active or role != User.Role.ADMINISTRATOR):
        if (
            not User.objects.filter(is_active=True, role=User.Role.ADMINISTRATOR)
            .exclude(pk=pk)
            .exists()
        ):
            raise ValidationError("Keep at least one active administrator.")
        if target.pk == request.user.pk:
            raise ValidationError("You cannot deactivate or demote your own administrator account.")

    changes = {
        field: value
        for field, value in {"role": role, "is_active": is_active}.items()
        if getattr(target, field) != value
    }
    if not changes:
        raise ValidationError("Choose a different role or status before saving.")
    check_assignments(target, role=role, is_active=is_active)
    target.update_with_revision(revision, **changes)
    if changes.get("is_active") is False:
        User.objects.filter(pk=pk).update(session_version=F("session_version") + 1)
    if "role" in changes:
        audit_account(
            request,
            "account.role_change",
            AuditEvent.Result.SUCCESS,
            actor=request.user,
            target=target,
            fields=["role"],
        )
    if "is_active" in changes:
        audit_account(
            request,
            "account.activate" if is_active else "account.deactivate",
            AuditEvent.Result.SUCCESS,
            actor=request.user,
            target=target,
            fields=["is_active"],
        )
