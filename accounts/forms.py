from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm
from django.core.validators import validate_email

from .models import User


class SignInForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].validators.append(validate_email)
        self.fields["username"].widget.attrs.update(
            {"class": "form-control", "type": "email", "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs["class"] = "form-control"

    def clean_username(self):
        return self.cleaned_data["username"].lower()


class AccountCreationForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("full_name", "email", "role")


class AccountAccessForm(forms.Form):
    role = forms.ChoiceField(choices=User.Role.choices)
    is_active = forms.ChoiceField(
        label="Status", choices=(("active", "Active"), ("inactive", "Deactivated"))
    )
    revision = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def clean_is_active(self):
        return self.cleaned_data["is_active"] == "active"
