from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_safe

from clients.models import Client
from clients.search import possible_duplicates, search_clients
from config.models import ConcurrentEditError
from documents.models import Document
from work.models import Task

from .forms import (
    CaseClientForm,
    CaseCreationForm,
    CaseEditForm,
    ClientEditForm,
    ClientForm,
    ClientSearchForm,
    DocumentEditForm,
    RevisionForm,
    TaskAssignmentForm,
    TaskReassignmentForm,
)
from .models import Case, CaseMembership
from .policies import (
    Action,
    audit_events_visible_to,
    can_archive_clients,
    can_complete_task,
    can_link_clients,
    case_allows,
    cases_visible_to,
    clients_visible_to,
    deadlines_visible_to,
    documents_visible_to,
    editable_case_fields,
    has_capability,
    tasks_visible_to,
)
from .services import (
    audit_change,
    audit_event,
    case_for_action,
    create_case,
    link_client,
    lock_actor,
    lock_visible_client,
    require_editable,
)

FORM_METHODS = ["GET", "HEAD", "POST"]


@login_required
@require_safe
def index(request):
    user = request.user
    cases = cases_visible_to(user)
    query = request.GET.get("q", "").strip()[:200]
    results = (
        cases.filter(Q(number__icontains=query) | Q(title__icontains=query)) if query else cases
    )
    totals = {
        "Cases": cases.filter(is_archived=False).count(),
        "Clients": clients_visible_to(user).filter(status=Client.Status.ACTIVE).count(),
        "Documents": documents_visible_to(user).filter(state=Document.State.ACTIVE).count(),
        "Tasks": tasks_visible_to(user).filter(is_archived=False).count(),
        "Deadlines": deadlines_visible_to(user).filter(is_archived=False).count(),
    }
    return render(
        request,
        "cases/index.html",
        {
            "cases": results,
            "totals": totals,
            "query": query,
            "can_create": has_capability(user, Action.CREATE_RECORDS),
            "can_view_audit": has_capability(user, Action.VIEW_AUDIT),
        },
    )


@login_required
@require_safe
def detail(request, pk):
    user = request.user
    case = get_object_or_404(cases_visible_to(user), pk=pk)
    editable = case.status != Case.Status.CLOSED and not case.is_archived
    tasks = tasks_visible_to(user).filter(case=case, is_archived=False)
    can_assign = editable and case_allows(user, Action.ASSIGN_TASKS, case)
    can_complete = editable and has_capability(user, Action.COMPLETE_TASK)
    return render(
        request,
        "cases/detail.html",
        {
            "case": case,
            "clients": clients_visible_to(user).filter(
                case_links__case=case, case_links__is_active=True
            ),
            "documents": documents_visible_to(user).filter(case=case).order_by("state", "title"),
            "task_rows": [
                (
                    task,
                    can_complete
                    and task.assignee_id == user.pk
                    and task.status != Task.Status.DONE,
                )
                for task in tasks.select_related("assignee").order_by("due_at", "pk")
            ],
            "can_edit": editable and case_allows(user, Action.EDIT_CASE, case),
            "can_link_clients": editable and can_link_clients(user, case),
            "can_manage_documents": editable and case_allows(user, Action.MANAGE_DOCUMENTS, case),
            "can_assign": can_assign,
            "can_archive": case.status == Case.Status.CLOSED
            and not case.is_archived
            and case_allows(user, Action.ARCHIVE_CASE, case),
        },
    )


@login_required
@require_safe
def client_index(request):
    form = ClientSearchForm(request.GET)
    page = None
    if form.is_valid():
        data = form.cleaned_data
        clients = clients_visible_to(request.user).filter(
            status=data["status"] or Client.Status.ACTIVE
        )
        clients = search_clients(clients, data["q"]).order_by("name", "pk")
        paginator = Paginator(clients, 25)
        number = data["page"] or 1
        if number > paginator.num_pages:
            form.add_error("page", "This page does not exist.")
        else:
            page = paginator.page(number)
    if page is not None and request.method == "GET":
        audit_event(request, "client.search" if form.cleaned_data["q"] else "client.list", "client")
    response = render(
        request,
        "cases/clients.html",
        {
            "form": form,
            "page": page,
            "can_create": has_capability(request.user, Action.CREATE_RECORDS),
        },
        status=200 if page is not None else 400,
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required
@require_safe
def client_detail(request, pk):
    client = get_object_or_404(clients_visible_to(request.user), pk=pk)
    cases = (
        cases_visible_to(request.user)
        .filter(client_links__client=client, client_links__is_active=True)
        .order_by("number", "pk")
    )
    if request.method == "GET":
        audit_change(request, "client.view", client)
    active = client.status == Client.Status.ACTIVE
    return render(
        request,
        "cases/client_detail.html",
        {
            "client_record": client,
            "cases": cases,
            "can_edit": active,
            "can_archive": active and can_archive_clients(request.user),
        },
    )


@login_required
@require_safe
def audit_index(request):
    if not has_capability(request.user, Action.VIEW_AUDIT):
        raise PermissionDenied
    page = Paginator(audit_events_visible_to(request.user).select_related("actor"), 50)
    return render(request, "cases/audit.html", {"page": page.get_page(request.GET.get("page"))})


def form_response(request, form, title, *, status=None, **context):
    return render(
        request,
        "accounts/form.html",
        {
            "form": form,
            "title": title,
            "submit_label": title,
            **context,
        },
        status=status or (400 if request.method == "POST" else 200),
    )


def revision_response(request, form, title, record, action, case_id, *, fixed_changes=None):
    if form.is_valid():
        changes = (
            fixed_changes
            if fixed_changes is not None
            else {field: form.cleaned_data[field] for field in form.fields if field != "revision"}
        )
        try:
            record.update_with_revision(form.cleaned_data["revision"], **changes)
        except ConcurrentEditError as exc:
            form.add_error(None, str(exc))
            return form_response(request, form, title, status=409)
        audit_change(request, action, record, changes)
        return redirect("cases:detail", pk=case_id)
    return form_response(request, form, title)


def duplicate_warning(actor, form, client=None):
    if form.cleaned_data["confirm_duplicate"]:
        return []
    matches = possible_duplicates(
        clients_visible_to(actor), form.cleaned_data, exclude_pk=client.pk if client else None
    )
    if matches:
        form.fields["confirm_duplicate"].widget = forms.CheckboxInput()
    return matches


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def client_create(request):
    user = lock_actor(request)
    if not has_capability(user, Action.CREATE_RECORDS):
        raise PermissionDenied
    form = ClientForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        matches = duplicate_warning(user, form)
        if matches:
            return form_response(request, form, "Create client", matches=matches, status=200)
        client = form.save(commit=False)
        client.created_by = user
        client.save()
        audit_change(request, "client.create", client)
        return redirect("cases:client_detail", pk=client.pk)
    return form_response(request, form, "Create client")


def client_for_request(request, pk):
    if request.method == "POST":
        return lock_visible_client(lock_actor(request), pk)
    return get_object_or_404(clients_visible_to(request.user), pk=pk)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def client_edit(request, pk):
    client = client_for_request(request, pk)
    if client.status == Client.Status.ARCHIVED:
        raise PermissionDenied
    title = "Save client details"
    context = {"client_record": client}
    form = ClientEditForm(
        request.POST if request.method == "POST" else None,
        instance=client,
        initial={"revision": client.revision},
    )
    if request.method == "GET":
        audit_change(request, "client.view", client)
    if form.is_valid():
        if form.cleaned_data["revision"] != client.revision:
            form.add_error(None, "This record has changed. Reload it before saving.")
            return form_response(request, form, title, status=409, **context)
        changes = {
            field: form.cleaned_data[field]
            for field in form.Meta.fields
            if form.cleaned_data[field] != form.initial[field]
        }
        if changes.keys() & {"name", "email", "phone"}:
            matches = duplicate_warning(request.user, form, client)
            if matches:
                return form_response(request, form, title, matches=matches, status=200, **context)
        if changes:
            client.update_with_revision(form.cleaned_data["revision"], **changes)
            audit_change(request, "client.edit", client, changes)
        return redirect("cases:client_detail", pk=pk)
    return form_response(request, form, title, **context)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def client_archive(request, pk):
    client = client_for_request(request, pk)
    if not can_archive_clients(request.user):
        raise PermissionDenied
    if client.status == Client.Status.ARCHIVED:
        return HttpResponse("This client is already archived.", status=409)
    form = RevisionForm(
        request.POST if request.method == "POST" else None, initial={"revision": client.revision}
    )
    title = "Archive client"
    context = {
        "client_record": client,
        "description": "Archiving removes the client from active lists and case selectors. "
        "Existing case links are retained.",
    }
    if form.is_valid():
        try:
            client.update_with_revision(
                form.cleaned_data["revision"], status=Client.Status.ARCHIVED
            )
        except ConcurrentEditError as exc:
            form.add_error(None, str(exc))
            return form_response(request, form, title, status=409, **context)
        audit_change(request, "client.archive", client, ["status"])
        return redirect("cases:client_detail", pk=pk)
    return form_response(request, form, title, **context)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_link_client(request, pk):
    case = case_for_action(request, pk, Action.EDIT_CASE)
    if not can_link_clients(request.user, case):
        raise PermissionDenied
    require_editable(case)
    form = CaseClientForm(
        request.POST if request.method == "POST" else None, actor=request.user, case=case
    )
    if form.is_valid():
        try:
            link = link_client(case, form.cleaned_data["client"], request.user)
        except ValidationError as exc:
            form.add_error("client", exc)
        else:
            audit_change(request, "case.client.link", link, ["clients"])
            return redirect("cases:detail", pk=pk)
    return form_response(request, form, "Link client", case_record=case)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_create(request):
    user = lock_actor(request)
    if not has_capability(user, Action.CREATE_RECORDS):
        raise PermissionDenied
    form = CaseCreationForm(request.POST if request.method == "POST" else None, actor=user)
    if form.is_valid():
        case = create_case(form, user)
        audit_change(request, "case.create", case)
        return redirect("cases:detail", pk=case.pk)
    return form_response(request, form, "Create case")


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_edit(request, pk):
    case = case_for_action(request, pk, Action.EDIT_CASE)
    require_editable(case)
    form = CaseEditForm(
        request.POST if request.method == "POST" else None,
        instance=case,
        editable_fields=editable_case_fields(request.user, case),
    )
    return revision_response(request, form, "Save case details", case, "case.edit", case.pk)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_archive(request, pk):
    case = case_for_action(request, pk, Action.ARCHIVE_CASE)
    if case.status != Case.Status.CLOSED or case.is_archived:
        return HttpResponse("Only closed, unarchived cases can be archived.", status=409)
    form = RevisionForm(
        request.POST if request.method == "POST" else None, initial={"revision": case.revision}
    )
    return revision_response(
        request,
        form,
        "Archive case",
        case,
        "case.archive",
        case.pk,
        fixed_changes={"is_archived": True},
    )


@login_required
@require_safe
def document_download(request, pk, document_pk):
    document = get_object_or_404(documents_visible_to(request.user), case_id=pk, pk=document_pk)
    try:
        file = document.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    return FileResponse(
        file,
        as_attachment=True,
        filename=document.original_filename,
        content_type="application/octet-stream",
    )


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def document_edit(request, pk, document_pk):
    case = case_for_action(request, pk, Action.MANAGE_DOCUMENTS)
    document = get_object_or_404(documents_visible_to(request.user), case=case, pk=document_pk)
    require_editable(case)
    if document.state != Document.State.ACTIVE:
        raise PermissionDenied
    form = DocumentEditForm(request.POST if request.method == "POST" else None, instance=document)
    return revision_response(
        request, form, "Save document details", document, "document.edit", case.pk
    )


def lock_assignee_membership(case, assignee):
    get_object_or_404(
        CaseMembership.objects.select_for_update(no_key=True, of=("self",)),
        case=case,
        user=assignee,
        is_active=True,
        user__is_active=True,
    )


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def task_assign(request, pk):
    case = case_for_action(request, pk, Action.ASSIGN_TASKS)
    require_editable(case)
    form = TaskAssignmentForm(request.POST if request.method == "POST" else None, case=case)
    if form.is_valid():
        task = form.save(commit=False)
        lock_assignee_membership(case, task.assignee)
        task.case = case
        task.created_by = request.user
        task.save()
        audit_change(request, "task.assign", task, ["assignee"])
        return redirect("cases:detail", pk=pk)
    return form_response(request, form, "Assign task")


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def task_reassign(request, pk, task_pk):
    case = case_for_action(request, pk, Action.ASSIGN_TASKS)
    task = get_object_or_404(
        tasks_visible_to(request.user), case=case, pk=task_pk, is_archived=False
    )
    require_editable(case)
    if task.status == Task.Status.DONE:
        raise PermissionDenied
    form = TaskReassignmentForm(
        request.POST if request.method == "POST" else None,
        case=case,
        initial={"revision": task.revision, "assignee": task.assignee_id},
    )
    if form.is_valid():
        lock_assignee_membership(case, form.cleaned_data["assignee"])
    return revision_response(request, form, "Reassign task", task, "task.reassign", pk)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def task_complete(request, pk, task_pk):
    case = case_for_action(request, pk, Action.COMPLETE_TASK)
    task = get_object_or_404(
        tasks_visible_to(request.user), case=case, pk=task_pk, is_archived=False
    )
    require_editable(case)
    if not can_complete_task(request.user, task):
        raise PermissionDenied
    if task.status == Task.Status.DONE:
        return HttpResponse("This task is already complete.", status=409)
    form = RevisionForm(
        request.POST if request.method == "POST" else None, initial={"revision": task.revision}
    )
    return revision_response(
        request,
        form,
        "Complete task",
        task,
        "task.complete",
        pk,
        fixed_changes={"status": Task.Status.DONE, "completed_at": timezone.now()},
    )
