from django.urls import path

from . import views

app_name = "cases"
urlpatterns = [
    path("", views.index, name="index"),
    path("cases/<int:pk>/", views.detail, name="detail"),
]
