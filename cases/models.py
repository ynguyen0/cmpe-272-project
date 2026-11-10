from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from config.models import RevisionedModel, enum_check, nonblank_check, revision_checks


class Case(RevisionedModel):
    class Status(models.TextChoices):
        OPEN = "Open"
        ON_HOLD = "On hold"
        CLOSED = "Closed"

    class Type(models.TextChoices):
        CIVIL = "Civil"
        CRIMINAL = "Criminal"
        FAMILY = "Family"
        CORPORATE = "Corporate"
        OTHER = "Other"

    number = models.CharField(max_length=40, unique=True)
    court_docket_number = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=200)
    type = models.CharField(max_length=15, choices=Type.choices, default=Type.OTHER)
    summary = models.CharField(max_length=2000, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    clients = models.ManyToManyField("clients.Client", through="CaseClient", related_name="cases")
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="CaseMembership", related_name="cases"
    )
    responsible_attorney = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="responsible_cases"
    )
    opened_on = models.DateField(default=timezone.localdate)
    closed_on = models.DateField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_cases"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["number"]
        indexes = [
            models.Index(fields=["is_archived", "status", "opened_on"], name="case_worklist_idx"),
            models.Index(fields=["court_docket_number"], name="case_docket_idx"),
        ]
        constraints = [
            *revision_checks(),
            nonblank_check("number"),
            nonblank_check("title"),
            enum_check("type", ["Civil", "Criminal", "Family", "Corporate", "Other"]),
            enum_check("status", ["Open", "On hold", "Closed"]),
            models.CheckConstraint(
                condition=Q(closed_on__isnull=True) | Q(closed_on__gte=F("opened_on")),
                name="case_dates_ordered",
            ),
            models.CheckConstraint(
                condition=(Q(status="Closed", closed_on__isnull=False))
                | (~Q(status="Closed") & Q(closed_on__isnull=True)),
                name="case_closed_date_matches_status",
            ),
            models.CheckConstraint(
                condition=Q(is_archived=False) | Q(status="Closed"),
                name="case_archive_requires_closed",
            ),
        ]

    def __str__(self):
        return f"{self.number}: {self.title}"


class CaseClient(RevisionedModel):
    class Relationship(models.TextChoices):
        CLIENT = "Client"
        PLAINTIFF = "Plaintiff"
        DEFENDANT = "Defendant"
        OTHER = "Other"

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="client_links")
    client = models.ForeignKey(
        "clients.Client", on_delete=models.PROTECT, related_name="case_links"
    )
    relationship = models.CharField(max_length=15, choices=Relationship.choices, default="Client")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cases_case_clients"  # Reuse the original link table without losing rows.
        unique_together = [("case", "client")]
        indexes = [models.Index(fields=["client", "is_active"], name="caseclient_access_idx")]
        constraints = [
            *revision_checks(),
            enum_check("relationship", ["Client", "Plaintiff", "Defendant", "Other"]),
        ]


class CaseMembership(RevisionedModel):
    class Responsibility(models.TextChoices):
        LEAD = "Lead attorney"
        ATTORNEY = "Attorney"
        SUPPORT = "Support"

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships"
    )
    responsibility = models.CharField(
        max_length=20, choices=Responsibility.choices, default="Support"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cases_case_members"
        unique_together = [("case", "user")]
        indexes = [models.Index(fields=["user", "is_active", "case"], name="membership_access_idx")]
        constraints = [
            *revision_checks(),
            enum_check("responsibility", ["Lead attorney", "Attorney", "Support"]),
            models.UniqueConstraint(
                fields=["case"],
                condition=Q(is_active=True, responsibility="Lead attorney"),
                name="one_active_lead_per_case",
            ),
        ]
