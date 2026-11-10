from django.conf import settings
from django.db import models
from django.db.models import Q

from config.models import RevisionedModel, enum_check, nonblank_check, revision_checks


class Task(RevisionedModel):
    class Status(models.TextChoices):
        TODO = "To do"
        IN_PROGRESS = "In progress"
        DONE = "Done"

    class Priority(models.TextChoices):
        LOW = "Low"
        NORMAL = "Normal"
        HIGH = "High"

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="tasks")
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=2000, blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.TODO)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_tasks"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["assignee", "is_archived", "status", "due_at"], name="task_worklist_idx"
            ),
            models.Index(fields=["case", "status"], name="task_case_status_idx"),
        ]
        constraints = [
            *revision_checks(),
            nonblank_check("title"),
            enum_check("status", ["To do", "In progress", "Done"]),
            enum_check("priority", ["Low", "Normal", "High"]),
            models.CheckConstraint(
                condition=Q(status="Done", completed_at__isnull=False)
                | (~Q(status="Done") & Q(completed_at__isnull=True)),
                name="task_completion_matches_status",
            ),
        ]


class Deadline(RevisionedModel):
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
    due_at = models.DateTimeField()
    type = models.CharField(max_length=10, choices=Type.choices)
    responsible_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="responsible_deadlines"
    )
    notes = models.CharField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_deadlines",
        null=True,
        blank=True,
    )
    completion_notes = models.CharField(max_length=500, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["responsible_user", "is_archived", "status", "due_at"],
                name="deadline_worklist_idx",
            ),
            models.Index(fields=["case", "status", "due_at"], name="deadline_case_dates_idx"),
        ]
        constraints = [
            *revision_checks(),
            nonblank_check("title"),
            enum_check("type", ["Hearing", "Filing", "Meeting", "Other"]),
            enum_check("status", ["Pending", "Completed", "Cancelled"]),
            models.CheckConstraint(
                condition=Q(
                    status="Pending",
                    completed_at__isnull=True,
                    completed_by__isnull=True,
                    completion_notes="",
                )
                | (
                    Q(
                        status__in=["Completed", "Cancelled"],
                        completed_at__isnull=False,
                        completed_by__isnull=False,
                    )
                    & ~Q(completion_notes__regex=r"^\s*$")
                ),
                name="deadline_completion_consistent",
            ),
        ]
