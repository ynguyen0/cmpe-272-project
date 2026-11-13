from uuid import uuid4

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils.crypto import salted_hmac

from audit.models import AuditEvent


def audit_account(request, action, result, *, actor=None, target=None, fields=()):
    if not hasattr(request, "audit_correlation_id"):
        request.audit_correlation_id = uuid4()
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        resource_type="user",
        resource_id=str(target.pk) if target is not None else "",
        result=result,
        correlation_id=request.audit_correlation_id,
        changed_fields=list(fields),
    )


def lock_login_identity(email):
    """Serialize attempts for a normalized identity across all web workers."""
    digest = salted_hmac("accounts.login_throttle", email, algorithm="sha256").digest()
    lock_key = int.from_bytes(digest[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])
    return digest.hex()


class AccountResetTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return f"{super()._make_hash_value(user, timestamp)}:{user.session_version}"


reset_tokens = AccountResetTokenGenerator()


class MaximumPasswordLengthValidator:
    def validate(self, password, user=None):
        if len(password) > 128:
            raise ValidationError(self.get_help_text(), code="password_too_long")

    def get_help_text(self):
        return "Your password must contain at most 128 characters."
