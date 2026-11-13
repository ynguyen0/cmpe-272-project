from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    INTERNAL_RESET_SESSION_TOKEN,
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetView,
    redirect_to_login,
)
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_safe

from audit.models import AuditEvent

from .forms import AccountAccessForm, AccountCreationForm, SignInForm
from .middleware import start_session
from .models import User
from .security import audit_account, reset_tokens
from .services import (
    change_account_access,
    check_login,
    lock_account_administration,
    require_administrator,
)


class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = SignInForm

    @method_decorator(sensitive_post_parameters())
    @transaction.atomic
    def post(self, request, *args, **kwargs):
        form = self.get_form()
        outcome = check_login(form)
        if outcome == "limited":
            error = form.get_invalid_login_error()
            return self.render_to_response(
                self.get_context_data(
                    form=self.get_form_class()(request),
                    login_error=error.messages[0],
                ),
                status=429,
            )
        if outcome == "valid":
            return self.form_valid(form)
        return self.form_invalid(form)

    def form_valid(self, form):
        if self.request.user.is_authenticated:
            self.request.session.cycle_key()
        response = super().form_valid(form)
        start_session(self.request)
        user = form.get_user()
        audit_account(
            self.request, "auth.login", AuditEvent.Result.SUCCESS, actor=user, target=user
        )
        return response


class SignOutView(LogoutView):
    def post(self, request, *args, **kwargs):
        actor = request.user if request.user.is_authenticated else None
        response = super().post(request, *args, **kwargs)
        audit_account(request, "auth.logout", AuditEvent.Result.SUCCESS, actor=actor)
        return response


class ChangePasswordView(PasswordChangeView):
    template_name = "accounts/form.html"
    success_url = reverse_lazy("accounts:password_change")
    extra_context = {"submit_label": "Change password"}

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        user = User.objects.select_for_update().get(pk=request.user.pk)
        if not user.is_active or not constant_time_compare(
            user.get_session_auth_hash(), request.user.get_session_auth_hash()
        ):
            logout(request)
            return redirect_to_login(request.path)
        request.user = user
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        audit_account(
            self.request,
            "auth.password_change",
            AuditEvent.Result.SUCCESS,
            actor=form.user,
            target=form.user,
        )
        messages.success(self.request, "Your password has been changed.")
        return response


class RequestPasswordResetView(PasswordResetView):
    title = "Reset your password"
    template_name = "accounts/form.html"
    email_template_name = "accounts/reset_email.txt"
    subject_template_name = "accounts/reset_subject.txt"
    token_generator = reset_tokens
    success_url = reverse_lazy("accounts:password_reset_done")
    extra_context = {"submit_label": "Send reset link"}


class ConfirmPasswordResetView(PasswordResetConfirmView):
    template_name = "accounts/reset_confirm.html"
    token_generator = reset_tokens
    success_url = reverse_lazy("accounts:password_reset_complete")

    @transaction.atomic
    def form_valid(self, form):
        user = User.objects.select_for_update().get(pk=form.user.pk)
        session_token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
        if not user.is_active or not self.token_generator.check_token(user, session_token):
            self.validlink = False
            return self.render_to_response(self.get_context_data())
        form.user = user
        response = super().form_valid(form)
        audit_account(self.request, "auth.password_reset", AuditEvent.Result.SUCCESS, target=user)
        return response

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        return user if user is not None and user.is_active else None


@login_required
@require_safe
def account_list(request):
    require_administrator(request)
    return render(request, "accounts/list.html", {"accounts": User.objects.order_by("email")})


@sensitive_post_parameters()
@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def account_create(request):
    require_administrator(request)
    form = AccountCreationForm(request.POST if request.method == "POST" else None)
    status = 200
    if request.method == "POST":
        if form.is_valid():
            try:
                with transaction.atomic():
                    lock_account_administration(request)
                    # Check the identity again after serializing administrator creates.
                    if User.objects.filter(email=form.instance.email).exists():
                        raise ValidationError("An account with this email already exists.")
                    target = form.save()
                    audit_account(
                        request,
                        "account.create",
                        AuditEvent.Result.SUCCESS,
                        actor=request.user,
                        target=target,
                        fields=["name", "email", "role", "is_active"],
                    )
            except PermissionDenied:
                audit_account(
                    request, "account.create", AuditEvent.Result.DENIED, actor=request.user
                )
                raise
            except ValidationError as exc:
                form.add_error("email", exc)
            else:
                messages.success(request, "Account created.")
                return redirect("accounts:list")
        audit_account(request, "account.create", AuditEvent.Result.FAILURE, actor=request.user)
        status = 400
    return render(
        request,
        "accounts/form.html",
        {"form": form, "title": "Create account", "submit_label": "Create account"},
        status=status,
    )


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def account_access(request, pk):
    require_administrator(request)
    target = get_object_or_404(User, pk=pk)
    form = AccountAccessForm(
        request.POST if request.method == "POST" else None,
        initial={
            "role": target.role,
            "is_active": "active" if target.is_active else "inactive",
            "revision": target.revision,
        },
    )
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    lock_account_administration(request)
                    change_account_access(request, pk, **form.cleaned_data)
            except PermissionDenied:
                audit_account(
                    request,
                    "account.access_change",
                    AuditEvent.Result.DENIED,
                    actor=request.user,
                    target=target,
                )
                raise
            except ValidationError as exc:
                form.add_error(None, exc)
                status = 409
            else:
                messages.success(request, "Account access updated.")
                return redirect("accounts:list")
        audit_account(
            request,
            "account.access_change",
            AuditEvent.Result.FAILURE,
            actor=request.user,
            target=target,
        )
    return render(
        request,
        "accounts/form.html",
        {
            "form": form,
            "title": "Edit account access",
            "submit_label": "Save changes",
            "target": target,
        },
        status=status,
    )
