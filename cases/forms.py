from django import forms
from django.utils import timezone

from accounts.models import User
from clients.models import Client
from clients.search import PHONE_INPUT, phone_digits
from documents.models import Document
from work.models import Task

from .models import Case
from .policies import clients_visible_to, eligible_assignees


class StrictFields:
    def clean(self):
        cleaned = super().clean()
        if self.data.keys() - self.fields.keys() - {"csrfmiddlewaretoken"}:
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
        choices=[("", "All unarchived statuses"), *Case.Status.choices, ("archived", "Archived")],
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


class DocumentEditForm(StrictFields, forms.ModelForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = Document
        fields = ("title", "category", "revision")


class TaskAssignmentForm(StrictFields, forms.ModelForm):
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
