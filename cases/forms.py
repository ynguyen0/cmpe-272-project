from django import forms

from accounts.models import User
from clients.models import Client
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


class ClientCreationForm(StrictFields, forms.ModelForm):
    class Meta:
        model = Client
        fields = ("name", "type", "email", "phone", "address", "notes")


class CaseCreationForm(StrictFields, forms.ModelForm):
    client = forms.ModelChoiceField(queryset=Client.objects.none())
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
        self.fields["client"].queryset = (
            clients_visible_to(actor).filter(status=Client.Status.ACTIVE).order_by("name", "pk")
        )
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
