from django.conf import settings
from django.db import models

from config.models import RevisionedModel, enum_check, nonblank_check, revision_checks


class Client(RevisionedModel):
    class Type(models.TextChoices):
        INDIVIDUAL = "Individual"
        ORGANIZATION = "Organization"

    class Status(models.TextChoices):
        ACTIVE = "Active"
        ARCHIVED = "Archived"

    name = models.CharField(max_length=150)
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=500, blank=True)
    notes = models.CharField(max_length=2000, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status", "name"], name="client_status_name_idx")]
        constraints = [
            *revision_checks(),
            nonblank_check("name"),
            enum_check("type", ["Individual", "Organization"]),
            enum_check("status", ["Active", "Archived"]),
        ]

    def __str__(self):
        return self.name
