import json
import logging
import re
import traceback
from datetime import UTC, datetime

from .request_context import correlation_id


class RedactRecoveryURL(logging.Filter):
    token_path = re.compile(r"(/accounts/reset/[^/\s?]+/)[^/\s?]+")

    def filter(self, record):
        message = record.getMessage()
        sanitized = self.token_path.sub(r"\1[redacted]", message)
        if sanitized != message:
            record.msg = sanitized
            record.args = ()
        return True


class RedactRequestQuery(logging.Filter):
    # Client search terms can contain confidential contact information.
    request_query = re.compile(r"""(?P<path>(?<!\S)/[^?\s"']*)\?[^\s"']+""")

    def filter(self, record):
        message = record.getMessage()
        sanitized = self.request_query.sub(r"\g<path>?[redacted]", message)
        if sanitized != message:
            record.msg = sanitized
            record.args = ()
        return True


class JSONFormatter(logging.Formatter):
    """One physical JSON line; never serialize request objects or arbitrary extras."""

    def format(self, record):
        # Format a copy so sanitization does not mutate another handler's record.
        safe = logging.makeLogRecord(record.__dict__.copy())
        RedactRecoveryURL().filter(safe)
        RedactRequestQuery().filter(safe)
        request = getattr(record, "request", None)
        request_id = getattr(request, "correlation_id", None) or correlation_id.get()
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": str(request_id) if request_id else "-",
            "message": safe.getMessage(),
        }
        for name in ("method", "route", "status", "duration_seconds"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        if record.exc_info and record.exc_info[0]:
            payload["exception_type"] = record.exc_info[0].__name__
            # Exception values/locals may contain passwords, queries or client data.
            payload["stack"] = traceback.format_tb(record.exc_info[2])
        return json.dumps(payload, ensure_ascii=True)
