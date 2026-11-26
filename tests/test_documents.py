import os
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client as Browser
from django.test import override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.urls import reverse
from PIL import Image
from pypdf import PdfWriter

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case
from documents.models import Document
from documents.uploads import MAX_DOCUMENT_BYTES
from documents.validation import MEDIA_TYPES

from .test_foundation import SeededTestCase


def sample_docx():
    stream = BytesIO()
    with ZipFile(stream, "w") as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        package.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Fictional test</w:t></w:r></w:p></w:body></w:document>",
        )
    return stream.getvalue()


def sample_pdf(*, encrypted=False):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("fictional-password")
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def sample_image(format):
    stream = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(stream, format=format)
    return stream.getvalue()


class DocumentManagementTests(SeededTestCase):
    def setUp(self):
        self.case = Case.objects.get(number="DEMO-ALPHA")
        self.attorney = User.objects.get(email="attorney.a@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.upload_url = reverse("cases:document_upload", args=[self.case.pk])
        self.list_url = reverse("cases:documents", args=[self.case.pk])
        self.client.force_login(self.attorney)

    def data(self, filename="fictional.txt", contents=b"Fictional document."):
        return {
            "title": "Fictional evidence",
            "category": "Evidence",
            "description": "Fictional upload description",
            # The header is intentionally generic. Bytes and extension determine the format.
            "file": SimpleUploadedFile(filename, contents, content_type="application/octet-stream"),
        }

    def download_url(self, document):
        return reverse("cases:document_download", args=[self.case.pk, document.pk])

    def storage_files(self):
        return {p for p in settings.PRIVATE_MEDIA_ROOT.rglob("*") if p.is_file()}

    def test_formats_preserve_identical_bytes_and_generated_unique_keys(self):
        before = self.storage_files()
        samples = [
            ("pdf", sample_pdf()),
            ("docx", sample_docx()),
            ("txt", b"Fictional text."),
            ("jpg", sample_image("JPEG")),
            ("jpeg", sample_image("JPEG")),
            ("png", sample_image("PNG")),
            ("txt", b"Another fictional text."),
        ]
        for ext, content in samples:
            with self.subTest(ext=ext):
                title = f"Fictional {ext} document"
                response = self.client.post(
                    self.upload_url, self.data(f"same-name.{ext}", content) | {"title": title}
                )
                self.assertRedirects(response, self.list_url, fetch_redirect_response=False)
                document = Document.objects.filter(title=title).latest("pk")
                self.assertEqual(document.media_type, MEDIA_TYPES[f".{ext}"])
                self.assertEqual(document.uploaded_by, self.attorney)
                self.assertEqual(document.description, "Fictional upload description")
                self.assertRegex(document.file.name, rf"^cases/{self.case.pk}/[0-9a-f]{{32}}$")
                response = self.client.get(self.download_url(document))
                self.assertEqual(b"".join(response.streaming_content), content)
                self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertIn(
                    f'attachment; filename="same-name.{ext}"',
                    response.headers["Content-Disposition"],
                )
        self.assertEqual(len(self.storage_files() - before), len(samples))
        self.assertEqual(Document.objects.filter(original_filename="same-name.txt").count(), 2)
        self.assertEqual(
            AuditEvent.objects.filter(action="document.upload", result="success").count(),
            len(samples),
        )
        self.assertEqual(
            AuditEvent.objects.filter(action="document.download").count(), len(samples)
        )

    def test_prohibited_uploads_and_size_boundary(self):
        before = self.storage_files()
        disallowed = [
            ("fictional.exe", b"MZ Fictional"),
            ("fictional.pdf.exe", sample_pdf()),
            ("fake.jpg", b"Fictional text"),
            ("mislabeled.png", sample_image("JPEG")),
            ("fake.pdf", b"%PDF-1.7 Fictional %%EOF"),
            ("protected.pdf", sample_pdf(encrypted=True)),
            ("broken.png", sample_image("PNG")[:-8]),
            ("broken.docx", b"PK\x03\x04 Fictional"),
            ("empty.txt", b""),
            ("html.txt", b"<!doctype html><script>fictional()</script>"),
            ("binary.txt", b"Fictional\x00binary"),
            ("large.txt", b"x" * (MAX_DOCUMENT_BYTES + 1)),
        ]
        for filename, content in disallowed:
            with self.subTest(filename=filename):
                self.assertEqual(
                    self.client.post(self.upload_url, self.data(filename, content)).status_code, 400
                )
        raw = encode_multipart(BOUNDARY, self.data()).replace(
            b'filename="fictional.txt"', b'filename="../fictional.txt"'
        )
        self.assertEqual(
            self.client.generic(
                "POST", self.upload_url, raw, content_type=MULTIPART_CONTENT
            ).status_code,
            400,
        )
        self.assertFalse(Document.objects.filter(title="Fictional evidence").exists())
        self.assertEqual(self.storage_files(), before)
        self.assertEqual(
            self.client.post(
                self.upload_url, self.data(contents=b"x" * MAX_DOCUMENT_BYTES)
            ).status_code,
            302,
        )
        self.assertEqual(Document.objects.get(title="Fictional evidence").size, MAX_DOCUMENT_BYTES)

    def test_rollback_cleans_published_bytes_if_audit_fails(self):
        before = self.storage_files()
        with (
            patch("documents.services.audit_change", side_effect=RuntimeError("audit failure")),
            self.assertRaisesMessage(RuntimeError, "audit failure"),
        ):
            self.client.post(self.upload_url, self.data())
        self.assertEqual(self.storage_files(), before)
        self.assertFalse(Document.objects.filter(title="Fictional evidence").exists())

    def test_upload_requires_sign_in_staff_grant_and_csrf(self):
        anonymous = Browser()
        self.assertEqual(anonymous.post(self.upload_url, self.data()).status_code, 302)

        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.upload_url, self.data()).status_code, 403)

        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.attorney)
        self.assertEqual(browser.post(self.upload_url, self.data()).status_code, 403)
        self.assertFalse(Document.objects.filter(title="Fictional evidence").exists())

    def test_edit_and_archive_preserve_storage_and_hide_document_from_active_list(self):
        self.client.post(self.upload_url, self.data())
        document = Document.objects.get(title="Fictional evidence")
        edit_url = reverse("cases:document_edit", args=[self.case.pk, document.pk])
        archive_url = reverse("cases:document_archive", args=[self.case.pk, document.pk])
        changes = {
            "title": "Fictional revised",
            "category": "Contract",
            "description": "Revised",
            "revision": document.revision,
        }
        self.assertEqual(
            self.client.post(edit_url, changes | {"file": self.data()["file"]}).status_code, 400
        )
        self.assertEqual(self.client.post(edit_url, changes).status_code, 302)
        self.assertEqual(self.client.post(edit_url, changes).status_code, 409)
        self.assertContains(
            self.client.get(self.list_url, {"category": "Contract"}), changes["title"]
        )
        self.assertNotContains(
            self.client.get(self.list_url, {"category": "Evidence"}), changes["title"]
        )
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(archive_url).status_code, 403)
        self.client.force_login(self.attorney)
        original_key = document.file.name
        document.refresh_from_db()
        self.assertEqual(
            self.client.post(archive_url, {"revision": document.revision}).status_code, 400
        )
        archive = {"revision": document.revision, "archive_reason": "Fictional revised record"}
        self.assertEqual(self.client.post(archive_url, archive).status_code, 302)
        self.assertEqual(self.client.post(archive_url, archive).status_code, 409)
        document.refresh_from_db()
        self.assertEqual(document.archived_by, self.attorney)
        self.assertEqual(document.file.name, original_key)
        self.assertNotContains(self.client.get(self.list_url), changes["title"])
        self.assertContains(
            self.client.get(self.list_url, {"state": "Archived"}), archive["archive_reason"]
        )
        self.assertEqual(
            b"".join(self.client.get(self.download_url(document)).streaming_content),
            b"Fictional document.",
        )
        events = AuditEvent.objects.filter(resource_type="document", resource_id=str(document.pk))
        # Order independent: the shared audit writer sorts field names so that
        # equivalent changes always produce identical rows.
        self.assertCountEqual(
            events.get(action="document.edit").changed_fields,
            ["title", "category", "description"],
        )
        self.assertTrue(events.filter(action="document.archive").exists())

    @override_settings(DOCUMENT_REQUIRE_SCAN=True, DOCUMENT_CLAMDSCAN="/test/clamdscan")
    def test_hosted_scan_requires_success_before_publishing_or_downloading(self):
        before = self.storage_files()
        legacy = self.case.documents.get(state="Active")
        self.assertEqual(self.client.get(self.download_url(legacy)).status_code, 404)
        for result, status in ((1, 400), (2, 503)):
            with patch(
                "documents.scanning.subprocess.run", return_value=SimpleNamespace(returncode=result)
            ):
                self.assertEqual(self.client.post(self.upload_url, self.data()).status_code, status)
            self.assertEqual(self.storage_files(), before)
            self.assertFalse(Document.objects.filter(title="Fictional evidence").exists())

        def check_private_staging(args, **kwargs):
            self.assertEqual(args[:3], ["/test/clamdscan", "--fdpass", "--no-summary"])
            self.assertEqual(kwargs["timeout"], 30)
            staged = Path(args[-1])
            self.assertFalse(staged.is_relative_to(settings.PRIVATE_MEDIA_ROOT))
            self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
            self.assertEqual(staged.read_bytes(), b"Fictional document.")
            self.assertEqual(self.storage_files(), before)
            return SimpleNamespace(returncode=0)

        with patch("documents.scanning.subprocess.run", side_effect=check_private_staging):
            self.assertEqual(self.client.post(self.upload_url, self.data()).status_code, 302)
        document = Document.objects.get(title="Fictional evidence")
        self.assertIsNotNone(document.malware_scanned_at)
        self.assertEqual(
            b"".join(self.client.get(self.download_url(document)).streaming_content),
            b"Fictional document.",
        )

    def test_orphan_cleanup_respects_references_and_grace_period(self):
        root = settings.PRIVATE_MEDIA_ROOT
        referenced = Path(self.case.documents.get(state="Active").file.path)
        fresh = root / "cases" / str(self.case.pk) / ("a" * 32)
        abandoned = fresh.with_name("b" * 32)
        for path in (fresh, abandoned):
            path.write_bytes(b"Fictional orphan.")
        os.utime(abandoned, (1, 1))
        original_mtime = referenced.stat().st_mtime
        os.utime(referenced, (1, 1))
        try:
            output = StringIO()
            call_command("cleanup_orphan_documents", stdout=output)
            self.assertIn("Found 1", output.getvalue())
            self.assertTrue(abandoned.exists())
            call_command("cleanup_orphan_documents", "--delete", stdout=StringIO())
            self.assertFalse(abandoned.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(referenced.exists())
        finally:
            fresh.unlink(missing_ok=True)
            abandoned.unlink(missing_ok=True)
            os.utime(referenced, (original_mtime, original_mtime))
