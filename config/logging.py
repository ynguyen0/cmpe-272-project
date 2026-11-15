import logging
import re


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
