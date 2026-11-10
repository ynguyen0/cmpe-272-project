from django.conf import settings
from django.db import models


class Event(models.Model):
    """Initial audit schema; automatic capture and tamper protection are LOG-01 work."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=80)
    resource_type = models.CharField(max_length=40)
    resource_id = models.CharField(max_length=80, blank=True)
    result = models.CharField(max_length=20)
    correlation_id = models.UUIDField()
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
