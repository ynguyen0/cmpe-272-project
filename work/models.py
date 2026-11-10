from django.conf import settings
from django.db import models


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "To do"
        IN_PROGRESS = "In progress"
        DONE = "Done"

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=2000, blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    due_date = models.DateField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.TODO)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_tasks"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Deadline(models.Model):
    class Type(models.TextChoices):
        HEARING = "Hearing"
        FILING = "Filing"
        MEETING = "Meeting"
        OTHER = "Other"

    class Status(models.TextChoices):
        PENDING = "Pending"
        COMPLETED = "Completed"
        CANCELLED = "Cancelled"

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="deadlines")
    title = models.CharField(max_length=200)
    date = models.DateField()
    type = models.CharField(max_length=10, choices=Type.choices)
    notes = models.CharField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
