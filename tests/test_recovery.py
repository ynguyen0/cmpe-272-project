"""DEL-02: restore a real PostgreSQL snapshot and its private documents together."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from django.core.management import call_command
from django.db import connection
from django.test import TransactionTestCase
from psycopg import sql

from documents.models import Document


class RecoveryTests(TransactionTestCase):
    def test_restore_database_and_documents_then_authorize_downloads(self):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": "Fictional-recovery-passphrase-73!"}):
            call_command("seed_demo", stdout=StringIO())
        expected = {}
        for document in Document.objects.all():
            with document.file.open("rb") as source:
                expected[document.file.name] = hashlib.sha256(source.read()).hexdigest()
        config = connection.settings_dict
        recovery_name = f"test_lexflow_recovery_{uuid4().hex}"
        params = {
            "host": config["HOST"],
            "port": config["PORT"],
            "user": config["USER"],
            "password": config["PASSWORD"],
            "sslmode": config["OPTIONS"]["sslmode"],
            "dbname": "postgres",
            "autocommit": True,
        }
        env = {
            **os.environ,
            "PGHOST": str(config["HOST"]),
            "PGPORT": str(config["PORT"]),
            "PGUSER": str(config["USER"]),
            "PGPASSWORD": str(config["PASSWORD"]),
            "PGSSLMODE": config["OPTIONS"]["sslmode"],
            "POSTGRES_DB": recovery_name,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
        }
        with tempfile.TemporaryDirectory(prefix="lexflow-recovery-") as directory:
            root = Path(directory)
            call_command("backup_lexflow", root, stdout=StringIO())
            (backup,) = root.glob("lexflow-*")
            self.assertEqual((backup / "database.dump").stat().st_mode & 0o777, 0o600)
            media = root / "restored-media"
            media.mkdir(mode=0o700)
            with tarfile.open(backup / "documents.tar") as archive:
                archive.extractall(media, filter="data")
            # This database name is generated here; never restore over development data.
            with psycopg.connect(**params) as admin:
                admin.execute(
                    sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                        sql.Identifier(recovery_name)
                    )
                )
                try:
                    subprocess.run(
                        [
                            "pg_restore",
                            "--exit-on-error",
                            "--no-owner",
                            "--no-password",
                            "--dbname",
                            recovery_name,
                            str(backup / "database.dump"),
                        ],
                        env=env,
                        check=True,
                        capture_output=True,
                    )
                    # A separate process proves reads come from the restored DB and files,
                    # without routing any request to the source database or media tree.
                    script = """
import sys
import hashlib
import json
from pathlib import Path
import django
django.setup()
from django.test import Client, override_settings
from django.urls import reverse
from accounts.models import User
from cases.models import Case
from documents.models import Document
from django.conf import settings
media = Path(sys.argv[1])
expected = json.loads(sys.argv[2])
storage = {**settings.STORAGES, "default": {
    "BACKEND": "documents.storage.PrivateFileSystemStorage", "OPTIONS": {"location": media}}}
with override_settings(STORAGES=storage, PRIVATE_MEDIA_ROOT=media):
    browser = Client()
    browser.force_login(User.objects.get(email="attorney.a@example.test"))
    case = Case.objects.get(number="DEMO-ALPHA")
    assert case.clients.exists() and case.memberships.filter(is_active=True).exists()
    docs = list(Document.objects.filter(case=case))
    assert {doc.state for doc in docs} == {"Active", "Archived"}
    for doc in docs:
        url = reverse("cases:document_download", args=[case.pk, doc.pk])
        response = browser.get(url)
        assert response.status_code == 200
        restored = (media / doc.file.name).read_bytes()
        assert b"".join(response.streaming_content) == restored
        assert hashlib.sha256(restored).hexdigest() == expected[doc.file.name]
        outsider = Client()
        outsider.force_login(User.objects.get(email="attorney.b@example.test"))
        assert outsider.get(url).status_code == 404
print("Restored active/archived byte equality, relationships, and download permissions passed.")
"""
                    result = subprocess.run(
                        [sys.executable, "-c", script, str(media), json.dumps(expected)],
                        env=env,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("download permissions passed", result.stdout)
                finally:
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(recovery_name)
                        )
                    )
