from django.conf import settings
from django.contrib.auth import SESSION_KEY, logout
from django.utils.cache import patch_cache_control
from django.utils.timezone import now

from audit.models import AuditEvent

from .security import audit_account

SESSION_STARTED_AT = "account_session_started_at"
SESSION_LAST_SEEN_AT = "account_session_last_seen_at"


def start_session(request):
    timestamp = int(now().timestamp())
    request.session[SESSION_STARTED_AT] = timestamp
    request.session[SESSION_LAST_SEEN_AT] = timestamp


class AccountSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if SESSION_KEY in request.session:
            user = request.user
            timestamp = int(now().timestamp())
            started = request.session.get(SESSION_STARTED_AT, timestamp)
            last_seen = request.session.get(SESSION_LAST_SEEN_AT, timestamp)
            if not user.is_authenticated:
                # An inactive or revoked account cannot keep its old session.
                request.session.flush()
            elif (
                timestamp - started >= settings.SESSION_ABSOLUTE_AGE
                or timestamp - last_seen >= settings.SESSION_COOKIE_AGE
            ):
                audit_account(
                    request, "auth.session_expired", AuditEvent.Result.SUCCESS, actor=user
                )
                logout(request)
            else:
                request.session[SESSION_STARTED_AT] = started
                request.session[SESSION_LAST_SEEN_AT] = timestamp
        return self.get_response(request)


class PrivateResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith("/static/"):
            patch_cache_control(response, no_store=True, private=True)
        reset_path = request.path.startswith("/accounts/reset/")
        if reset_path and not request.path.endswith("/set-password/"):
            response["Referrer-Policy"] = "no-referrer"
        return response
