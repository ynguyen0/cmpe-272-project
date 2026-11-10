from django.conf import settings
from django.db import models


class Case(models.Model):
    class Status(models.TextChoices):
        OPEN = "Open"
        ON_HOLD = "On hold"
        CLOSED = "Closed"

    number = models.CharField(max_length=40, unique=True)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    clients = models.ManyToManyField("clients.Client", related_name="cases")
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="cases")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_cases"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return f"{self.number}: {self.title}"
