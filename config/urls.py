from django.urls import include, path

from .observability import health, metrics
from .views import home
from .wireframe import wireframe

urlpatterns = [
    path("", home, name="home"),
    path("health", health, name="health"),
    path("metrics", metrics, name="metrics"),
    path("wireframe/", wireframe, name="wireframe"),
    path("accounts/", include("accounts.urls")),
    path("", include("cases.urls")),
]
