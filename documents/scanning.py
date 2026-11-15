"""Submit private staged files to the configured local ClamAV daemon."""

import subprocess

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


class ScanUnavailable(Exception):
    pass


def scan_path(path):
    if not settings.DOCUMENT_CLAMDSCAN:
        raise ScanUnavailable
    try:
        result = subprocess.run(
            [settings.DOCUMENT_CLAMDSCAN, "--fdpass", "--no-summary", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScanUnavailable from exc
    if result.returncode == 1:
        raise ValidationError("The file did not pass the malware scan.")
    if result.returncode != 0:
        raise ScanUnavailable
    return timezone.now()


def scan_upload(file):
    if settings.DOCUMENT_CLAMDSCAN or settings.DOCUMENT_REQUIRE_SCAN:
        return scan_path(file.temporary_file_path())
    return None
