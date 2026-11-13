from django.contrib.auth.views import PasswordResetCompleteView, PasswordResetDoneView
from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.SignInView.as_view(), name="login"),
    path("logout/", views.SignOutView.as_view(), name="logout"),
    path("password/change/", views.ChangePasswordView.as_view(), name="password_change"),
    path("password/reset/", views.RequestPasswordResetView.as_view(), name="password_reset"),
    path(
        "password/reset/sent/",
        PasswordResetDoneView.as_view(template_name="accounts/reset_sent.html"),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.ConfirmPasswordResetView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        PasswordResetCompleteView.as_view(template_name="accounts/reset_complete.html"),
        name="password_reset_complete",
    ),
    path("manage/", views.account_list, name="list"),
    path("manage/create/", views.account_create, name="create"),
    path("manage/<int:pk>/", views.account_access, name="access"),
]
