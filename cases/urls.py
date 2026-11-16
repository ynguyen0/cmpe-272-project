from django.urls import path

from . import views

app_name = "cases"
urlpatterns = [
    path("", views.index, name="index"),
    path("clients/", views.client_index, name="clients"),
    path("clients/new/", views.client_create, name="client_create"),
    path("clients/<int:pk>/", views.client_detail, name="client_detail"),
    path("clients/<int:pk>/edit/", views.client_edit, name="client_edit"),
    path("clients/<int:pk>/archive/", views.client_archive, name="client_archive"),
    path("audit/", views.audit_index, name="audit"),
    path("cases/new/", views.case_create, name="create"),
    path("cases/<int:pk>/", views.detail, name="detail"),
    path("cases/<int:pk>/clients/link/", views.case_link_client, name="link_client"),
    path("cases/<int:pk>/edit/", views.case_edit, name="edit"),
    path("cases/<int:pk>/team/", views.case_team, name="team"),
    path("cases/<int:pk>/status/", views.case_status, name="status"),
    path("cases/<int:pk>/archive/", views.case_archive, name="archive"),
    path("cases/<int:pk>/documents/", views.document_index, name="documents"),
    path("cases/<int:pk>/documents/upload/", views.document_upload, name="document_upload"),
    path(
        "cases/<int:pk>/documents/<int:document_pk>/archive/",
        views.document_archive,
        name="document_archive",
    ),
    path(
        "cases/<int:pk>/documents/<int:document_pk>/download/",
        views.document_download,
        name="document_download",
    ),
    path(
        "cases/<int:pk>/documents/<int:document_pk>/edit/",
        views.document_edit,
        name="document_edit",
    ),
    path("cases/<int:pk>/tasks/assign/", views.task_assign, name="task_assign"),
    path("cases/<int:pk>/tasks/<int:task_pk>/reassign/", views.task_reassign, name="task_reassign"),
    path("cases/<int:pk>/tasks/<int:task_pk>/complete/", views.task_complete, name="task_complete"),
    path("cases/<int:pk>/tasks/<int:task_pk>/edit/", views.task_edit, name="task_edit"),
    path("cases/<int:pk>/tasks/<int:task_pk>/status/", views.task_status, name="task_status"),
    path("work/", views.work_index, name="work"),
]
