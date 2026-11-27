"""Transactional, redacted audit capture for LOG-01.

Teammates: :func:`record_event` is the only supported way to write an
:class:`~audit.models.AuditEvent`. Call it from inside the same
``transaction.atomic()`` block as the change it describes, so the change and its
event commit together or neither commits (backlog rule G5)::

    with transaction.atomic():
        case.update_with_revision(expected_revision, status="On hold")
        record_event(
            actor=request.user,
            action=Action.CASE_STATUS_CHANGED,
            resource_type=Resource.CASE,
            resource_id=case.pk,
            result=AuditEvent.Result.SUCCESS,
            changed_fields=["status"],
        )

What this helper will **not** let you do, by design:

* store a submitted value of any kind — ``changed_fields`` takes field *names*
  only, checked against :attr:`AuditEvent.CHANGE_FIELDS`;
* store free text that could forge log structure — action, resource type and
  resource ID are pattern-checked;
* store passwords, tokens, client contact/notes text or file contents, because
  there is no parameter that accepts them.

See ``docs/permissions-and-audit.md`` for the full usage note.
"""

import re
import uuid

from django.db import transaction

from config.request_context import correlation_id as _correlation_id

from .models import AuditEvent

# Actions read as "<resource>.<verb>", lowercase, so LOG-02 can filter on exact strings.
ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
RESOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# Generated identifiers only: primary keys, UUIDs, case numbers. Never an email or free text.
RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]*$")
MAX_ACTION = 80
MAX_RESOURCE_TYPE = 40
MAX_RESOURCE_ID = 80
MAX_CHANGED_FIELDS = 20


class Resource:
    """Resource type values. Add one here rather than passing an ad-hoc string."""

    USER = "user"
    SESSION = "session"
    CASE = "case"
    CASE_MEMBERSHIP = "case_membership"
    CASE_CLIENT = "case_client"
    CLIENT = "client"
    DOCUMENT = "document"
    TASK = "task"
    DEADLINE = "deadline"
    AUDIT_LOG = "audit_log"


class Action:
    """Action names.

    Member A owns the authentication, user-administration and audit entries.
    Members B and C: add your own constants here following ``<resource>.<verb>``
    with a verb from ``read``, ``searched``, ``created``, ``updated``,
    ``status_changed``, ``archived``, ``uploaded``, ``downloaded``, ``assigned``,
    ``linked``, ``unlinked``. Keeping them in one place keeps the LOG-02 action
    filter meaningful.
    """

    # Authentication and sessions (AUTH-01, AUTH-02).
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    LOGIN_BLOCKED = "auth.login_blocked"
    LOGOUT = "auth.logout"
    SESSION_REVOKED = "auth.session_revoked"

    # User administration (USER-01, USER-02).
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    USER_LIST_READ = "user.read"

    # Authorization outcomes (ACCESS-01).
    ACCESS_DENIED = "access.denied"
    VALIDATION_FAILED = "validation.failed"

    # Audit review (LOG-02).
    AUDIT_LOG_READ = "audit_log.read"

    # Baseline entries for the client, case, document, task and deadline screens.
    # Extend this list rather than passing a bare string, so the LOG-02 action
    # filter stays meaningful.
    CLIENT_CREATED = "client.created"
    CLIENT_UPDATED = "client.updated"
    CLIENT_READ = "client.read"
    CLIENT_SEARCHED = "client.searched"
    CLIENT_ARCHIVED = "client.archived"
    CASE_CREATED = "case.created"
    CASE_UPDATED = "case.updated"
    CASE_READ = "case.read"
    CASE_SEARCHED = "case.searched"
    CASE_STATUS_CHANGED = "case.status_changed"
    CASE_CLIENT_LINKED = "case_client.linked"
    CASE_CLIENT_UNLINKED = "case_client.unlinked"
    CASE_MEMBER_ASSIGNED = "case_membership.assigned"
    CASE_MEMBER_REMOVED = "case_membership.unlinked"
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_DOWNLOADED = "document.downloaded"
    DOCUMENT_UPDATED = "document.updated"
    DOCUMENT_READ = "document.read"
    DOCUMENT_ARCHIVED = "document.archived"
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_READ = "task.read"
    TASK_STATUS_CHANGED = "task.status_changed"
    DEADLINE_CREATED = "deadline.created"
    DEADLINE_UPDATED = "deadline.updated"
    DEADLINE_READ = "deadline.read"
    DEADLINE_STATUS_CHANGED = "deadline.status_changed"


def new_correlation_id() -> uuid.UUID:
    """Return a fresh correlation ID. The middleware calls this once per request."""
    return uuid.uuid4()


def set_correlation_id(value: uuid.UUID):
    """Bind ``value`` for the current request/task; returns a token for :func:`reset`."""
    return _correlation_id.set(value)


def reset_correlation_id(token) -> None:
    """Unbind the correlation ID set by :func:`set_correlation_id`."""
    _correlation_id.reset(token)


def get_correlation_id() -> uuid.UUID:
    """Return the current correlation ID, creating one outside a request.

    Management commands and tests have no middleware, so they still get a stable
    ID for the duration of their context rather than a different one per event.
    """
    value = _correlation_id.get()
    if value is None:
        value = new_correlation_id()
        _correlation_id.set(value)
    return value


def _clean_changed_fields(changed_fields) -> list[str]:
    """Return sorted, de-duplicated allowlisted field names, or raise ValueError.

    Checking in Python as well as in the database check constraint gives callers a
    readable error naming the offending field instead of an opaque IntegrityError.
    """
    if isinstance(changed_fields, str):
        raise ValueError("changed_fields must be a sequence of names, not a single string.")
    names = sorted({str(name) for name in changed_fields})
    unknown = [name for name in names if name not in AuditEvent.CHANGE_FIELDS]
    if unknown:
        raise ValueError(
            f"Not allowlisted audit field name(s): {', '.join(unknown)}. "
            "Audit events record field names only, never values. "
            "Add genuinely new field names to AuditEvent.CHANGE_FIELDS with a migration."
        )
    if len(names) > MAX_CHANGED_FIELDS:
        raise ValueError(f"At most {MAX_CHANGED_FIELDS} changed field names may be recorded.")
    return names


def _clean_token(value, pattern, limit, label) -> str:
    """Validate one short identifier against ``pattern`` so logs cannot be forged."""
    text = str(value).strip()
    if len(text) > limit:
        raise ValueError(f"{label} must be at most {limit} characters.")
    if not pattern.fullmatch(text):
        raise ValueError(f"{label} {text!r} is not a valid {label} name.")
    return text


def record_event(
    *,
    action: str,
    resource_type: str,
    result: str,
    actor=None,
    resource_id="",
    changed_fields=(),
    correlation_id: uuid.UUID | None = None,
    require_atomic: bool = False,
) -> AuditEvent:
    """Append one audit event and return it.

    Args:
        action: An :class:`Action` constant, e.g. ``Action.LOGIN_SUCCEEDED``.
        resource_type: A :class:`Resource` constant, e.g. ``Resource.CASE``.
        result: ``AuditEvent.Result.SUCCESS``, ``FAILURE`` or ``DENIED``.
        actor: The acting ``User``, or ``None`` for an unauthenticated request.
        resource_id: The target's generated ID. Never an email or free text.
        changed_fields: Allowlisted field *names* changed by a mutation.
        correlation_id: Defaults to this request's ID; pass one only to join
            events the middleware cannot see.
        require_atomic: Pass ``True`` at mutation call sites to assert the caller
            really did open a transaction, turning a silent accountability gap
            into a loud failure.

    Raises:
        ValueError: On an unknown action/resource/result, a malformed resource ID,
            or a field name that is not allowlisted. Nothing is written.
        RuntimeError: If ``require_atomic`` is set and no transaction is open.

    Called inside an open ``transaction.atomic()`` block, the event joins that
    transaction, so rolling the mutation back also discards the event.
    """
    if require_atomic and not transaction.get_connection().in_atomic_block:
        raise RuntimeError(
            "record_event(require_atomic=True) must run inside transaction.atomic() "
            "so the change and its audit event commit together (backlog rule G5)."
        )
    if result not in AuditEvent.Result.values:
        raise ValueError(f"Unknown audit result {result!r}; use AuditEvent.Result.")
    if actor is not None and getattr(actor, "pk", None) is None:
        raise ValueError("The audit actor must be a saved user, or None when unauthenticated.")
    event = AuditEvent(
        actor=actor,
        action=_clean_token(action, ACTION_PATTERN, MAX_ACTION, "action"),
        resource_type=_clean_token(
            resource_type, RESOURCE_PATTERN, MAX_RESOURCE_TYPE, "resource_type"
        ),
        resource_id=_clean_token(resource_id, RESOURCE_ID_PATTERN, MAX_RESOURCE_ID, "resource_id"),
        result=result,
        correlation_id=correlation_id or get_correlation_id(),
        changed_fields=_clean_changed_fields(changed_fields),
    )
    # atomic() here is a savepoint inside a caller's transaction and a transaction
    # of its own otherwise, so a lone event is never half-written either.
    with transaction.atomic():
        event.save()
    return event
