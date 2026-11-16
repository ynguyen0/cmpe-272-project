"""Per-request correlation ID for audit events (LOG-01)."""

from .services import new_correlation_id, reset_correlation_id, set_correlation_id


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
