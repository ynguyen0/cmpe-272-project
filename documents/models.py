import uuid

from django.conf import settings
from django.db import models


def private_upload_path(instance, filename):
    # Never trust a client filename as a storage path.
    return f"cases/{instance.case_id}/{uuid.uuid4().hex}"


class Document(models.Model):
    class Category(models.TextChoices):
        PLEADING = "Pleading"
        EVIDENCE = "Evidence"
        CORRESPONDENCE = "Correspondence"
        CONTRACT = "Contract"
        OTHER = "Other"

    class State(models.TextChoices):
        ACTIVE = "Active"
        ARCHIVED = "Archived"

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="documents")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices)
    state = models.CharField(max_length=10, choices=State.choices, default=State.ACTIVE)
    file = models.FileField(upload_to=private_upload_path, max_length=255)
    original_filename = models.CharField(max_length=255)
    media_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="archives"
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archive_reason = models.CharField(max_length=500, blank=True)
