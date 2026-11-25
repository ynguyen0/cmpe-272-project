import re
from datetime import UTC, datetime, time, timedelta

from django import forms
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from audit.services import RESOURCE_ID_PATTERN
from clients.models import Client
from clients.search import PHONE_INPUT, phone_digits
from documents.models import Document
from documents.validation import validate_upload
from work.models import Deadline, Task
from work.transitions import TASK_TRANSITIONS

from .models import Case
from .policies import clients_visible_to, eligible_assignees


class StrictFields:
    def clean(self):
        cleaned = super().clean()
        if (self.data.keys() | self.files.keys()) - self.fields.keys() - {"csrfmiddlewaretoken"}:
            raise forms.ValidationError("This request contains unsupported fields.")
        return cleaned


class RevisionForm(StrictFields, forms.Form):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class ClientForm(StrictFields, forms.ModelForm):
    confirm_duplicate = forms.BooleanField(
        required=False, label="Save anyway; this is a separate client record"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["confirm_duplicate"].widget = forms.HiddenInput()

    def clean_email(self):
        return self.cleaned_data["email"].lower()

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if not phone:
            return ""
        digits = phone_digits(phone)
        if not PHONE_INPUT.fullmatch(phone) or not 7 <= len(digits) <= 15:
            raise forms.ValidationError(
                "Enter 7 to 15 digits, using spaces, parentheses, hyphens, or a leading +."
            )
        return ("+" if phone.startswith("+") else "") + digits

    class Meta:
        model = Client
        fields = ("name", "type", "email", "phone", "address", "notes")


class ClientEditForm(ClientForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class ClientSearchForm(StrictFields, forms.Form):
    q = forms.CharField(required=False, max_length=150, label="Search clients")
    status = forms.ChoiceField(
        required=False,
        choices=[("", "Active"), (Client.Status.ARCHIVED, "Archived")],
    )
    page = forms.IntegerField(required=False, min_value=1)


class ClientLabel:
    def label_from_instance(self, client):
        return f"{client.name} (#{client.pk})"


class ClientChoiceField(ClientLabel, forms.ModelChoiceField):
    pass


class MultipleCaseChoices(forms.ModelMultipleChoiceField):
    def clean(self, value):
        if isinstance(value, (list, tuple)) and len(set(value)) != len(value):
            raise forms.ValidationError("Select each record only once.")
        return super().clean(value)


class ClientMultipleChoiceField(ClientLabel, MultipleCaseChoices):
    pass


def active_client_choices(actor):
    return clients_visible_to(actor).filter(status=Client.Status.ACTIVE).order_by("name", "pk")


class CaseClientForm(StrictFields, forms.Form):
    client = ClientChoiceField(queryset=Client.objects.none())

    def __init__(self, *args, actor, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = active_client_choices(actor).exclude(
            pk__in=case.client_links.filter(is_active=True).values("client_id")
        )


class CaseSearchForm(StrictFields, forms.Form):
    ORDERINGS = {
        "number": ("number",),
        "title": ("title", "number"),
        "recent": ("-opened_on", "number"),
        "oldest": ("opened_on", "number"),
    }
    q = forms.CharField(
        required=False,
        max_length=200,
        label="Search cases",
        widget=forms.TextInput(attrs={"type": "search"}),
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Unarchived"),
            ("open", "Not closed"),
            *Case.Status.choices,
            ("archived", "Archived"),
        ],
    )
    type = forms.ChoiceField(required=False, choices=[("", "All types"), *Case.Type.choices])
    sort = forms.ChoiceField(
        required=False,
        choices=[
            ("number", "Case reference"),
            ("title", "Title"),
            ("recent", "Newest opened"),
            ("oldest", "Oldest opened"),
        ],
        initial="number",
    )
    page = forms.IntegerField(required=False, min_value=1)


def active_users_with_role(role):
    return User.objects.filter(is_active=True, role=role).order_by("full_name", "pk")


def opened_date_field():
    return forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )


class CaseDateValidation:
    def clean_opened_on(self):
        date = self.cleaned_data["opened_on"] or self.initial.get("opened_on", timezone.localdate())
        if date > timezone.localdate():
            raise forms.ValidationError("The opened date cannot be in the future.")
        return date


class CaseCreationForm(StrictFields, CaseDateValidation, forms.ModelForm):
    client = ClientChoiceField(queryset=Client.objects.none())
    additional_clients = ClientMultipleChoiceField(
        queryset=Client.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    responsible_attorney = forms.ModelChoiceField(queryset=User.objects.none())
    assigned_staff = MultipleCaseChoices(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    opened_on = opened_date_field()

    class Meta:
        model = Case
        labels = {"summary": "Description"}
        fields = (
            "title",
            "type",
            "court_docket_number",
            "summary",
            "opened_on",
            "client",
            "additional_clients",
            "responsible_attorney",
            "assigned_staff",
        )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        clients = active_client_choices(actor)
        self.fields["client"].queryset = clients
        self.fields["additional_clients"].queryset = clients
        self.fields["assigned_staff"].queryset = active_users_with_role(User.Role.STAFF)
        self.fields["responsible_attorney"].queryset = active_users_with_role(User.Role.ATTORNEY)
        self.initial.setdefault("opened_on", timezone.localdate())
        if actor.role == User.Role.ATTORNEY:
            self.initial.setdefault("responsible_attorney", actor.pk)

    def clean_additional_clients(self):
        additional = self.cleaned_data["additional_clients"]
        primary = self.cleaned_data.get("client")
        if primary and any(client.pk == primary.pk for client in additional):
            raise forms.ValidationError("Select each client only once.")
        return additional


class CaseTeamForm(RevisionForm):
    responsible_attorney = forms.ModelChoiceField(queryset=User.objects.none())
    assigned_staff = MultipleCaseChoices(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select everyone who should have staff access to this case.",
    )

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_attorney"].queryset = active_users_with_role(User.Role.ATTORNEY)
        staff = active_users_with_role(User.Role.STAFF)
        self.fields["assigned_staff"].queryset = staff
        self.initial.update(
            revision=case.revision,
            responsible_attorney=case.responsible_attorney_id,
            assigned_staff=staff.filter(
                memberships__case=case,
                memberships__is_active=True,
            ).exclude(pk=case.responsible_attorney_id),
        )


class CaseStatusForm(RevisionForm):
    status = forms.ChoiceField(label="New status")
    responsible_attorney = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Replacement responsible attorney",
    )

    def __init__(self, *args, case, targets, replacements=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["revision"] = case.revision
        self.fields["status"].choices = [(status, status.label) for status in targets]
        if case.status == Case.Status.CLOSED:
            self.initial["status"] = Case.Status.OPEN
        if replacements is None:
            del self.fields["responsible_attorney"]
        else:
            self.fields["responsible_attorney"].queryset = replacements


class CaseEditForm(StrictFields, CaseDateValidation, forms.ModelForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    opened_on = opened_date_field()

    class Meta:
        model = Case
        labels = {"summary": "Description"}
        fields = ("title", "type", "court_docket_number", "summary", "opened_on", "revision")

    def __init__(self, *args, editable_fields, **kwargs):
        super().__init__(*args, **kwargs)
        for field in set(self.fields) - set(editable_fields) - {"revision"}:
            del self.fields[field]


class DocumentListForm(StrictFields, forms.Form):
    category = forms.ChoiceField(
        choices=[("", "All categories"), *Document.Category.choices], required=False
    )
    state = forms.ChoiceField(
        choices=[("", "Active"), (Document.State.ARCHIVED, "Archived")], required=False
    )
    page = forms.IntegerField(required=False, min_value=1)


class DocumentUploadForm(StrictFields, forms.ModelForm):
    class Meta:
        model = Document
        fields = ("title", "category", "description", "file")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "file": forms.FileInput(attrs={"accept": ".pdf,.docx,.txt,.jpg,.jpeg,.png"}),
        }

    def clean_file(self):
        file = self.cleaned_data["file"]
        self.detected_type = validate_upload(file)
        return file


class DocumentArchiveForm(RevisionForm):
    archive_reason = forms.CharField(label="Archive reason", max_length=500)


class DocumentEditForm(StrictFields, forms.ModelForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = Document
        fields = ("title", "category", "description", "revision")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class RequiredDateTimeField(forms.DateTimeField):
    def to_python(self, value):
        if isinstance(value, str) and value.strip() and not re.search(r"[T ]\d{2}:\d{2}", value):
            raise forms.ValidationError("Enter both a date and time.")
        return super().to_python(value)


def required_date_time_field():
    return RequiredDateTimeField(
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        help_text=f"Enter a date and time in the firm's {settings.TIME_ZONE} timezone.",
    )


class TaskAssignmentForm(StrictFields, forms.ModelForm):
    due_at = required_date_time_field()

    class Meta:
        model = Task
        fields = ("title", "description", "assignee", "priority", "due_at")

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = eligible_assignees(case)


class TaskReassignmentForm(RevisionForm):
    assignee = forms.ModelChoiceField(queryset=User.objects.none())

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = eligible_assignees(case)


class TaskDetailsForm(RevisionForm):
    """Edit a task's own details (TASK-02). Assignee changes use the reassign form."""

    title = forms.CharField(max_length=200)
    description = forms.CharField(
        max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    priority = forms.ChoiceField(choices=Task.Priority.choices)
    due_at = required_date_time_field()


class TaskStatusForm(RevisionForm):
    """Move a task between statuses (TASK-03).

    The choices offered are only those reachable from the task's current status,
    so an invalid transition cannot be selected. The view checks the transition
    again on save, because the field alone is not authorization.
    """

    status = forms.ChoiceField(choices=())

    def __init__(self, *args, current, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (value, value) for value in sorted(TASK_TRANSITIONS.get(current, ()))
        ]


class WorkFilterForm(StrictFields, forms.Form):
    """Filters for the personal and authorized work lists."""

    assignee = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    status = forms.ChoiceField(choices=[("", "Any")] + Task.Status.choices, required=False)
    priority = forms.ChoiceField(choices=[("", "Any")] + Task.Priority.choices, required=False)
    overdue = forms.BooleanField(required=False, label="Overdue only")
    window = forms.ChoiceField(
        choices=[("", "All"), ("overdue", "Overdue"), ("upcoming", "Due in the next 7 days")],
        required=False,
    )
    page = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = choices
        self.fields["assignee"].empty_label = "Anyone I can see"


class DeadlineForm(StrictFields, forms.ModelForm):
    """Record a new deadline on a case (DATE-01)."""

    due_at = required_date_time_field()

    class Meta:
        model = Deadline
        fields = ("title", "type", "due_at", "responsible_user", "notes")
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        # Responsibility stays inside the case team, which the composite
        # foreign key also enforces at the database level.
        self.fields["responsible_user"].queryset = eligible_assignees(case)


class DeadlineDetailsForm(RevisionForm):
    """Revise an existing deadline's fields (DATE-01)."""

    title = forms.CharField(max_length=200)
    type = forms.ChoiceField(choices=Deadline.Type.choices)
    due_at = required_date_time_field()
    responsible_user = forms.ModelChoiceField(queryset=User.objects.none())
    notes = forms.CharField(
        max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_user"].queryset = eligible_assignees(case)


class DeadlineResolutionForm(RevisionForm):
    """Complete or cancel a deadline, which always requires a written reason.

    DATE-01 makes resolution explicit: finishing related work never resolves a
    deadline on its own, so the actor, the instant and the note are all recorded
    here. The database's deadline_completion_consistent constraint rejects a
    resolved row without them.
    """

    status = forms.ChoiceField(
        choices=[
            (Deadline.Status.COMPLETED, Deadline.Status.COMPLETED),
            (Deadline.Status.CANCELLED, Deadline.Status.CANCELLED),
        ]
    )
    completion_notes = forms.CharField(
        max_length=500, widget=forms.Textarea(attrs={"rows": 3}), label="Reason"
    )

    def clean_completion_notes(self):
        notes = self.cleaned_data["completion_notes"].strip()
        if not notes:
            raise forms.ValidationError("Give a reason for resolving this deadline.")
        return notes


class DeadlineFilterForm(StrictFields, forms.Form):
    """Filters for the authorized deadline list."""

    responsible_user = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
    status = forms.ChoiceField(choices=[("", "Any")] + Deadline.Status.choices, required=False)
    type = forms.ChoiceField(choices=[("", "Any")] + Deadline.Type.choices, required=False)
    window = forms.ChoiceField(
        choices=[("", "All"), ("overdue", "Overdue"), ("upcoming", "Upcoming")], required=False
    )
    page = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsible_user"].queryset = choices
        self.fields["responsible_user"].empty_label = "Anyone I can see"


AUDIT_DEFAULT_DAYS = 7
AUDIT_MAX_DAYS = 31


class AuditActorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f"{user.full_name} ({user.email})"


class AuditFilterForm(StrictFields, forms.Form):
    """LOG-02 filters: actor, action, resource, and an inclusive UTC date range."""

    actor = AuditActorChoiceField(
        required=False, queryset=User.objects.order_by("email"), empty_label="Any actor"
    )
    action = forms.ChoiceField(required=False)
    resource_type = forms.ChoiceField(required=False, label="Record type")
    resource_id = forms.CharField(
        required=False,
        max_length=80,
        label="Record ID",
        validators=[
            RegexValidator(RESOURCE_ID_PATTERN, "Enter a record ID such as 12, without spaces.")
        ],
    )
    start = forms.DateField(
        required=False, label="From (UTC)", widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(
        required=False, label="To (UTC)", widget=forms.DateInput(attrs={"type": "date"})
    )
    page = forms.IntegerField(required=False, min_value=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        events = AuditEvent.objects.order_by()
        actions = events.values_list("action", flat=True).distinct().order_by("action")
        types = events.values_list("resource_type", flat=True).distinct().order_by("resource_type")
        self.fields["action"].choices = [("", "Any action"), *((a, a) for a in actions)]
        self.fields["resource_type"].choices = [("", "Any record"), *((t, t) for t in types)]

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        today = timezone.now().astimezone(UTC).date()
        start, end = cleaned.get("start"), cleaned.get("end")
        if end is None:
            end = today
        if start is None:
            start = end - timedelta(days=AUDIT_DEFAULT_DAYS - 1)
        if start > end:
            raise forms.ValidationError("The start date must be on or before the end date.")
        if (end - start).days >= AUDIT_MAX_DAYS:
            raise forms.ValidationError(f"Choose a date range of at most {AUDIT_MAX_DAYS} days.")
        cleaned["start"], cleaned["end"] = start, end
        return cleaned

    def filter(self, events):
        data = self.cleaned_data
        lower = datetime.combine(data["start"], time.min, tzinfo=UTC)
        upper = datetime.combine(data["end"] + timedelta(days=1), time.min, tzinfo=UTC)
        events = events.filter(occurred_at__gte=lower, occurred_at__lt=upper)
        if data["actor"] is not None:
            events = events.filter(actor=data["actor"])
        for field in ("action", "resource_type", "resource_id"):
            if data[field]:
                events = events.filter(**{field: data[field]})
        return events.order_by("-occurred_at", "-pk")


class GlobalSearchForm(StrictFields, forms.Form):
    """One query across authorized cases and clients (DASH-01, issue #17)."""

    q = forms.CharField(
        max_length=150,
        label="Search Cases And Clients",
        widget=forms.TextInput(attrs={"type": "search"}),
    )
