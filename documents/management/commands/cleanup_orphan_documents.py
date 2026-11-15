import re
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from documents.models import Document
from documents.services import lock_private_storage

GENERATED_KEY = re.compile(r"cases/[1-9][0-9]*/[a-f0-9]{32}(?:_[a-zA-Z0-9]{7})?")


class Command(BaseCommand):
    help = "Report or remove generated files older than 24 hours with no document record."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Remove the reported orphans.")

    @transaction.atomic
    def handle(self, *args, **options):
        lock_private_storage()
        root = settings.PRIVATE_MEDIA_ROOT
        cutoff = (timezone.now() - timedelta(hours=24)).timestamp()
        count = 0
        for path in (root / "cases").glob("*/*"):
            key = path.relative_to(root).as_posix()
            if not GENERATED_KEY.fullmatch(key) or path.is_symlink() or path.parent.is_symlink():
                continue
            try:
                if not path.is_file() or path.stat().st_mtime >= cutoff:
                    continue
            except FileNotFoundError:
                continue  # An upload rolling back may already have removed the file.
            if Document.objects.filter(file=key).exists():
                continue
            if options["delete"]:
                default_storage.delete(key)
            count += 1
        verb = "Removed" if options["delete"] else "Found"
        self.stdout.write(f"{verb} {count} abandoned document file(s).")
