from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from config.models import enum_check, nonblank_check


class AuditEvent(models.Model):
    """Append-only history, protected by a PostgreSQL trigger as well as actor FKs."""

    class Result(models.TextChoices):
        SUCCESS = "success"
        FAILURE = "failure"
        DENIED = "denied"

    CHANGE_FIELDS = [
        "name",
        "email",
        "role",
        "is_active",
        "title",
        "type",
        "summary",
        "status",
        "responsible_attorney",
        "opened_on",
        "closed_on",
        "relationship",
        "responsibility",
        "category",
        "state",
        "assignee",
        "priority",
        "due_at",
        "completed_at",
        "completed_by",
        "responsible_user",
        "is_archived",
        "clients",
        "members",
    ]

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=80)
    resource_type = models.CharField(max_length=40)
    resource_id = models.CharField(max_length=80, blank=True)
    result = models.CharField(max_length=20)
    correlation_id = models.UUIDField()
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    changed_fields = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        indexes = [
            models.Index(fields=["actor", "occurred_at"], name="audit_actor_time_idx"),
            models.Index(
                fields=["resource_type", "resource_id", "occurred_at"], name="audit_target_time_idx"
            ),
            models.Index(fields=["action", "occurred_at"], name="audit_action_time_idx"),
            models.Index(fields=["correlation_id"], name="audit_request_idx"),
        ]
        constraints = [
            nonblank_check("action"),
            nonblank_check("resource_type"),
            enum_check("result", ["success", "failure", "denied"]),
            models.CheckConstraint(
                condition=models.Q(
                    changed_fields__contained_by=[
                        "name",
                        "email",
                        "role",
                        "is_active",
                        "title",
                        "type",
                        "summary",
                        "status",
                        "responsible_attorney",
                        "opened_on",
                        "closed_on",
                        "relationship",
                        "responsibility",
                        "category",
                        "state",
                        "assignee",
                        "priority",
                        "due_at",
                        "completed_at",
                        "completed_by",
                        "responsible_user",
                        "is_archived",
                        "clients",
                        "members",
                    ]
                )
                & models.Q(changed_fields__len__lte=20),
                name="audit_change_fields_limited",
            ),
        ]
