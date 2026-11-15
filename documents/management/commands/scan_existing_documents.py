from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from audit.models import AuditEvent
from documents.models import Document
from documents.scanning import ScanUnavailable, scan_path


class Command(BaseCommand):
    help = "Scan existing private files before enabling their downloads in hosted mode."

    def handle(self, *args, **options):
        clean = blocked = 0
        for document in Document.objects.filter(malware_scanned_at__isnull=True).iterator():
            if not document.file.storage.exists(document.file.name):
                blocked += 1
                continue
            try:
                scanned_at = scan_path(document.file.path)
            except ValidationError:
                blocked += 1
                continue
            except ScanUnavailable as exc:
                raise CommandError(
                    "ClamAV is unavailable. Unverified files remain blocked."
                ) from exc
            with transaction.atomic():
                updated = Document.objects.filter(
                    pk=document.pk, malware_scanned_at__isnull=True
                ).update(malware_scanned_at=scanned_at)
                if updated:
                    AuditEvent.objects.create(
                        action="document.scan",
                        resource_type="document",
                        resource_id=str(document.pk),
                        result=AuditEvent.Result.SUCCESS,
                        correlation_id=uuid4(),
                    )
            clean += 1
        self.stdout.write(f"Verified {clean} document(s).")
        if blocked:
            raise CommandError(
                f"{blocked} document(s) are missing or failed the scan and remain blocked."
            )
