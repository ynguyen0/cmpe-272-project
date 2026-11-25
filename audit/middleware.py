"""Request-level audit plumbing: correlation IDs and access denials (LOG-01)."""

import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import AuditEvent
from .services import (
    Action,
    Resource,
    new_correlation_id,
    record_event,
    reset_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger("lexflow.audit")


class AuditCorrelationMiddleware:
    """Give every request one correlation ID shared by all of its audit events.

    LOG-01 requires a "request correlation ID" on each event so an administrator
    reviewing the log can group everything one request did — for example a
    permission denial and the read that triggered it. Views may also read
    ``request.correlation_id`` directly when they need to pass it somewhere the
    context variable cannot reach, such as a background command.

    The ID is generated here, never accepted from the client, so a caller cannot
    stitch their requests onto somebody else's trail.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = new_correlation_id()
        request.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)
        try:
            return self.get_response(request)
        finally:
            # Always unbind: worker threads and ASGI tasks are reused between requests.
            reset_correlation_id(token)


# Routes whose URL carries a nested record ID, most specific first.
NESTED_TARGETS = (
    ("document_pk", Resource.DOCUMENT, "documents.Document"),
    ("task_pk", Resource.TASK, "work.Task"),
    ("deadline_pk", Resource.DEADLINE, "work.Deadline"),
)
# Routes without a record ID, keyed by "namespace:url_name".
ROUTE_RESOURCES = {
    "cases:audit": Resource.AUDIT_LOG,
    "cases:clients": Resource.CLIENT,
    "cases:client_create": Resource.CLIENT,
    "cases:work": Resource.TASK,
    "cases:deadlines": Resource.DEADLINE,
}


def denial_target(request):
    """Return ``(resource_type, model_label, record_id)`` for the refused route.

    The target comes from the URL pattern, never from the response, so the
    event names only what the caller asked for — not anything they were shown.
    """
    match = getattr(request, "resolver_match", None)
    if match is None:
        return Resource.SESSION, None, ""
    kwargs = match.kwargs
    for key, resource_type, model_label in NESTED_TARGETS:
        if key in kwargs:
            return resource_type, model_label, kwargs[key]
    if match.namespace == "accounts":
        return Resource.USER, "accounts.User", kwargs.get("pk", "")
    if "pk" in kwargs:
        if match.url_name.startswith("client"):
            return Resource.CLIENT, "clients.Client", kwargs["pk"]
        return Resource.CASE, "cases.Case", kwargs["pk"]
    return ROUTE_RESOURCES.get(match.view_name, Resource.CASE), None, ""


def record_exists(model_label, record_id):
    from django.apps import apps

    return apps.get_model(model_label).objects.filter(pk=record_id).exists()


class AccessDenialAuditMiddleware:
    """Record refused requests as ``access.denied`` events (LOG-01, ACCESS-01).

    ``process_exception`` runs after the view's ``transaction.atomic()`` block
    has rolled back, so the denial event is written in its own transaction and
    survives the rollback of whatever the refused request tried to change.

    * ``PermissionDenied`` is always a denial.
    * ``Http404`` is a denial only when the requested record exists: scoped
      lookups return 404 for records outside the caller's assignments, so the
      caller cannot tell "hidden" from "missing". The event is visible only to
      auditors, so recording the ID discloses nothing to the caller.

    If writing the event fails, the request is still refused exactly as it
    would have been; the failure goes to the ``lexflow.audit`` logger instead.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, PermissionDenied | Http404):
            return None
        if getattr(request, "audit_denial_recorded", False):
            return None
        try:
            resource_type, model_label, record_id = denial_target(request)
            if isinstance(exception, Http404):
                if model_label is None or not record_exists(model_label, record_id):
                    return None
            user = getattr(request, "user", None)
            record_event(
                actor=user if user is not None and user.is_authenticated else None,
                action=Action.ACCESS_DENIED,
                resource_type=resource_type,
                resource_id=str(record_id),
                result=AuditEvent.Result.DENIED,
            )
            request.audit_denial_recorded = True
        except Exception as exc:  # noqa: BLE001 - a denial must never become a success
            logger.error("Could not record an access denial: %s", type(exc).__name__)
        return None
