"""Shared schema invariants and explicit optimistic writes for domain services."""

from django.db import models
from django.db.models import F, Q
from django.utils import timezone


def enum_check(field, choices):
    return models.CheckConstraint(
        condition=Q(**{f"{field}__in": list(choices)}),
        name=f"%(app_label)s_%(class)s_{field}_valid",
    )


def nonblank_check(field):
    return models.CheckConstraint(
        condition=~Q(**{f"{field}__regex": r"^\s*$"}),
        name=f"%(app_label)s_%(class)s_{field}_nonblank",
    )


def revision_checks():
    return [
        models.CheckConstraint(
            condition=Q(revision__gte=1), name="%(app_label)s_%(class)s_revision_positive"
        )
    ]


class ConcurrentEditError(Exception):
    """The record changed after the caller read its revision."""


class RevisionedModel(models.Model):
    revision = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def update_with_revision(self, expected_revision, **changes):
        """Atomic compare-and-swap. Call only after service authorization/validation.

        QuerySet.update intentionally bypasses save/signals; checks and FKs still run.
        Multi-record work must wrap this and its audit write in transaction.atomic().
        """
        writable = {
            field.name
            for field in self._meta.concrete_fields
            if field.editable and not field.primary_key
        } - {"revision", "updated_at", "created_at", "uploaded_at", "date_joined"}
        if (
            self.pk is None
            or type(expected_revision) is not int
            or expected_revision < 1
            or not changes
            or not changes.keys() <= writable
        ):
            raise ValueError(
                "Supply a saved record, positive revision, and editable field changes."
            )
        count = (
            type(self)
            .objects.filter(pk=self.pk, revision=expected_revision)
            .update(**changes, revision=F("revision") + 1, updated_at=timezone.now())
        )
        if count != 1:
            raise ConcurrentEditError("This record has changed. Reload it before saving.")
        self.refresh_from_db()
        return self
