import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from audit.models import Event
from cases.models import Case
from clients.models import Client
from documents.models import Document
from work.models import Deadline, Task


class Command(BaseCommand):
    help = (
        "Load fictional demo records idempotently (development/test only). Never prints passwords."
    )

    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_DATA:
            raise CommandError("Demo data is disabled in this environment.")
        password = os.environ.get("LEXFLOW_DEMO_PASSWORD", "")
        try:
            validate_password(password)
            if len(password) > 128:
                raise ValidationError("Demo password must be at most 128 characters.")
        except ValidationError as error:
            raise CommandError(
                "Set LEXFLOW_DEMO_PASSWORD to a valid 12–128 character password."
            ) from error
        written_files = []
        try:
            with transaction.atomic():
                self.load_records(password, written_files)
        except Exception:
            # File writes are outside database transactions; clean up only files this run wrote.
            for storage, name in written_files:
                storage.delete(name)
            raise
        self.stdout.write(
            self.style.SUCCESS("Fictional demo data loaded; existing passwords kept.")
        )

    def load_records(self, password, written_files):
        people = [
            ("admin", "Admin A", User.Role.ADMINISTRATOR, True),
            ("attorney.a", "Attorney A", User.Role.ATTORNEY, True),
            ("attorney.b", "Attorney B", User.Role.ATTORNEY, True),
            ("staff.a", "Staff A", User.Role.STAFF, True),
            ("inactive", "Inactive Demo", User.Role.STAFF, False),
        ]
        users = {}
        for key, name, role, active in people:
            users[key], _ = User.objects.get_or_create(
                email=f"{key}@example.test",
                defaults={
                    "full_name": name,
                    "role": role,
                    "is_active": active,
                    "password": make_password(password),
                },
            )
        a, b = users["attorney.a"], users["attorney.b"]
        clients = {}
        for key, name, creator in [
            ("alpha", "Fictional Avery Lane", a),
            ("beta", "Fictional Morgan Reed", b),
            ("shared", "Fictional Orchard Studio", a),
            ("unlinked.a", "Fictional Intake A", a),
            ("unlinked.b", "Fictional Intake B", b),
        ]:
            clients[key], _ = Client.objects.get_or_create(
                email=f"client.{key}@example.test",
                defaults={"name": name, "type": Client.Type.INDIVIDUAL, "created_by": creator},
            )
        alpha, _ = Case.objects.get_or_create(
            number="DEMO-ALPHA",
            defaults={"title": "Fictional Alpha matter", "created_by": a},
        )
        beta, _ = Case.objects.get_or_create(
            number="DEMO-BETA",
            defaults={"title": "Fictional Beta matter", "created_by": b},
        )
        alpha.members.add(a, users["staff.a"])
        beta.members.add(b)
        alpha.clients.add(clients["alpha"], clients["shared"])
        beta.clients.add(clients["beta"], clients["shared"])
        today = timezone.localdate()
        for offset in [-1, 0, 7, 8]:
            Task.objects.get_or_create(
                case=alpha,
                title=f"Demo task day {offset:+d}",
                defaults={
                    "assignee": users["staff.a"],
                    "due_date": today + timedelta(days=offset),
                    "created_by": a,
                },
            )
            Deadline.objects.get_or_create(
                case=alpha,
                title=f"Demo deadline day {offset:+d}",
                defaults={
                    "date": today + timedelta(days=offset),
                    "type": Deadline.Type.FILING,
                    "created_by": a,
                },
            )
        for state in Document.State:
            title = f"Fictional {state.lower()} sample"
            if Document.objects.filter(case=alpha, title=title).exists():
                continue
            content = b"Fictional LexFlow sample. No real client information.\n"
            doc = Document(
                case=alpha,
                title=title,
                category=Document.Category.OTHER,
                state=state,
                original_filename="fictional-sample.txt",
                media_type="text/plain",
                size=len(content),
                uploaded_by=a,
            )
            if state == Document.State.ARCHIVED:
                doc.archived_by = a
                doc.archived_at = timezone.now()
                doc.archive_reason = "Fictional archive demonstration"
            doc.file.save("fictional-sample.txt", ContentFile(content), save=False)
            written_files.append((doc.file.storage, doc.file.name))
            doc.save()
        Event.objects.get_or_create(
            action="demo.seed",
            correlation_id=uuid.UUID("77894a7c-cc34-4b6c-8ca0-778eb94801a1"),
            defaults={
                "actor": users["admin"],
                "resource_type": "demo",
                "resource_id": "baseline",
                "result": "success",
            },
        )
