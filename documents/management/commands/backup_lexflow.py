"""Back up the database and its referenced files from the same snapshot."""

import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.utils import validate_file_name
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from documents.models import Document
from documents.services import lock_private_storage


def dump_database(snapshot, path):
    config = connection.settings_dict
    env = {
        **os.environ,
        "PGHOST": str(config["HOST"]),
        "PGPORT": str(config["PORT"]),
        "PGUSER": str(config["USER"]),
        "PGPASSWORD": str(config["PASSWORD"]),
        "PGDATABASE": str(config["NAME"]),
        "PGSSLMODE": config["OPTIONS"]["sslmode"],
        "PGCONNECT_TIMEOUT": str(config["OPTIONS"]["connect_timeout"]),
        # Backup queries can legitimately exceed the interactive query limit.
        "PGOPTIONS": "-c statement_timeout=120000 -c lock_timeout=3000",
    }
    subprocess.run(
        [
            "pg_dump",
            "--no-password",
            "--format=custom",
            "--snapshot",
            snapshot,
            "--file",
            str(path),
        ],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=settings.DATABASE_BACKUP_TIMEOUT,
    )
    path.chmod(0o600)


def archive_files(path):
    with tarfile.open(path, "w") as archive:
        files = Document.objects.order_by("pk").values_list("file", "size")
        for key, size in files.iterator():
            validate_file_name(key, allow_relative_path=True)
            if default_storage.size(key) != size:
                raise CommandError(
                    "A stored document has a different size than its database record."
                )
            entry = tarfile.TarInfo(key)
            entry.size = size
            entry.mode = 0o600
            with default_storage.open(key, "rb") as source:
                archive.addfile(entry, source)
    path.chmod(0o600)


class Command(BaseCommand):
    help = (
        "Write a private PostgreSQL dump and its referenced document files to one backup directory."
    )

    def add_arguments(self, parser):
        parser.add_argument("destination", type=Path, help="Existing private backup directory.")

    def handle(self, *args, destination, **options):
        parent = destination.resolve()
        roots = (settings.PRIVATE_MEDIA_ROOT, settings.STATIC_ROOT, *settings.STATICFILES_DIRS)
        if not parent.is_dir() or any(parent.is_relative_to(root.resolve()) for root in roots):
            raise CommandError(
                "Choose an existing backup directory outside static and media roots."
            )
        timestamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
        target = parent / f"lexflow-{timestamp}-{uuid4().hex[:8]}"
        try:
            with tempfile.TemporaryDirectory(prefix=".lexflow-", dir=parent) as directory:
                staging = Path(directory)
                with transaction.atomic(durable=True):
                    with connection.cursor() as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                        cursor.execute("SELECT pg_export_snapshot()")
                        snapshot = cursor.fetchone()[0]
                    lock_private_storage(shared=True)
                    dump_database(snapshot, staging / "database.dump")
                    archive_files(staging / "documents.tar")
                staging.rename(target)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CommandError(
                "Backup failed. Check PostgreSQL access and private file storage."
            ) from exc
        self.stdout.write(f"Backup written to {target}")
