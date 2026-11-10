from django.contrib.auth.forms import AuthenticationForm


class SignInForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update(
            {"class": "form-control", "type": "email", "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs["class"] = "form-control"

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
