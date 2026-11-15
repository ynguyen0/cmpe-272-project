from django import forms

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


class ClientChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, client):
        return f"{client.name} (#{client.pk})"


def active_client_choices(actor):
    return clients_visible_to(actor).filter(status=Client.Status.ACTIVE).order_by("name", "pk")


class CaseClientForm(StrictFields, forms.Form):
    client = ClientChoiceField(queryset=Client.objects.none())

    def __init__(self, *args, actor, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = active_client_choices(actor).exclude(
            pk__in=case.client_links.filter(is_active=True).values("client_id")
        )


class CaseCreationForm(StrictFields, forms.ModelForm):
    client = ClientChoiceField(queryset=Client.objects.none())
    responsible_attorney = forms.ModelChoiceField(queryset=User.objects.none())

    class Meta:
        model = Case
        fields = (
            "title",
            "type",
            "court_docket_number",
            "summary",
            "client",
            "responsible_attorney",
        )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = active_client_choices(actor)
        self.fields["responsible_attorney"].queryset = User.objects.filter(
            is_active=True, role=User.Role.ATTORNEY
        ).order_by("full_name", "pk")
        if actor.role == User.Role.ATTORNEY:
            self.initial.setdefault("responsible_attorney", actor.pk)


class CaseEditForm(StrictFields, forms.ModelForm):
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = Case
        fields = ("title", "type", "court_docket_number", "summary", "revision")

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
