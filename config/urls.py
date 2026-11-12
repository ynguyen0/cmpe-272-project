from django.urls import include, path

from .wireframe import wireframe

urlpatterns = [
    path("wireframe/", wireframe, name="wireframe"),
    path("accounts/", include("accounts.urls")),
    path("", include("cases.urls")),
]
