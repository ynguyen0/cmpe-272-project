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
