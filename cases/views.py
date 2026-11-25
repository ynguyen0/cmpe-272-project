from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_safe

from accounts.models import User
from audit.models import AuditEvent
from audit.services import Action as AuditAction
from audit.services import Resource
from clients.models import Client
from clients.search import possible_duplicates, search_clients
from config.models import ConcurrentEditError
from documents.models import Document
from documents.scanning import ScanUnavailable, scan_upload
from documents.services import publish_document
from documents.uploads import safe_filename
from work.models import Deadline, Task
from work.transitions import DEADLINE_TRANSITIONS, TASK_TRANSITIONS, allows

from .dashboard import recent_activity, search_everything, work_cards
from .forms import (
    AuditFilterForm,
    CaseClientForm,
    CaseCreationForm,
    CaseEditForm,
    CaseSearchForm,
    CaseStatusForm,
    CaseTeamForm,
    ClientEditForm,
    ClientForm,
    ClientSearchForm,
    DeadlineDetailsForm,
    DeadlineFilterForm,
    DeadlineForm,
    DeadlineResolutionForm,
    DocumentArchiveForm,
    DocumentEditForm,
    DocumentListForm,
    DocumentUploadForm,
    GlobalSearchForm,
    RevisionForm,
    TaskAssignmentForm,
    TaskDetailsForm,
    TaskReassignmentForm,
    TaskStatusForm,
    WorkFilterForm,
    active_users_with_role,
)
from .models import Case, CaseMembership
from .policies import (
    Action,
    audit_events_visible_to,
    can_archive_clients,
    can_archive_documents,
    can_complete_task,
    can_link_clients,
    can_manage_case,
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
    CASE_TRANSITIONS,
    audit_change,
    audit_event,
    case_for_action,
    change_case_status,
    create_case,
    link_client,
    lock_actor,
    lock_visible_client,
    outstanding_work,
    require_editable,
    update_case_team,
)
from .worklists import (
    open_cases,
    overdue_filter,
    pending_upcoming_deadlines,
    unfinished_upcoming_tasks,
    upcoming_filter,  # noqa: F401 - re-exported for existing callers
)

FORM_METHODS = ["GET", "HEAD", "POST"]


@login_required
@require_safe
def dashboard(request):
    """What needs the signed-in user's attention (DASH-01).

    Counts and previews come from the same scoped queries as the lists they
    link to; a user with no assignments sees zeros and empty states only.
    """
    user = request.user
    now = timezone.now()
    context = {
        "cards": work_cards(user, now),
        "activity": recent_activity(user),
        "search_form": GlobalSearchForm(),
        "now": now,
        "can_create": has_capability(user, Action.CREATE_RECORDS),
        "can_view_audit": has_capability(user, Action.VIEW_AUDIT),
    }
    if request.method == "GET":
        audit_event(request, "dashboard.read", "dashboard")
    return render(request, "cases/dashboard.html", context)


@login_required
@require_safe
def search(request):
    """Search authorized cases and clients by names, references and metadata."""
    form = GlobalSearchForm(request.GET)
    results = None
    if form.is_valid():
        results = search_everything(request.user, form.cleaned_data["q"])
        if request.method == "GET":
            # Same actions as the case and client lists; the query text is never logged.
            audit_event(request, "case.search", "case")
            audit_event(request, "client.search", "client")
    response = render(
        request,
        "cases/search.html",
        {"form": form, "results": results},
        status=200 if results is not None else 400,
    )
    response["Referrer-Policy"] = "origin"
    return response


@login_required
@require_safe
def index(request):
    user = request.user
    cases = cases_visible_to(user)
    form = CaseSearchForm(request.GET)
    page = None
    if form.is_valid():
        data = form.cleaned_data
        results = cases.filter(is_archived=data["status"] == "archived")
        if data["status"] == "open":
            # The dashboard's "open cases" count links here (DASH-01).
            results = open_cases(user)
        elif data["status"] and data["status"] != "archived":
            results = results.filter(status=data["status"])
        if data["type"]:
            results = results.filter(type=data["type"])
        if query := data["q"]:
            results = results.filter(
                Q(number__icontains=query)
                | Q(title__icontains=query)
                | Q(court_docket_number__icontains=query)
            )
        ordered = results.order_by(*CaseSearchForm.ORDERINGS[data["sort"] or "number"])
        paginator = Paginator(ordered, 25)
        number = data["page"] or 1
        if number > paginator.num_pages:
            form.add_error("page", "This page does not exist.")
        else:
            page = paginator.page(number)
            if request.method == "GET":
                audit_event(request, "case.search" if query else "case.list", "case")
    totals = {
        "Cases": cases.filter(is_archived=False).count(),
        "Clients": clients_visible_to(user).filter(status=Client.Status.ACTIVE).count(),
        "Documents": documents_visible_to(user).filter(state=Document.State.ACTIVE).count(),
        "Tasks": tasks_visible_to(user).filter(is_archived=False).count(),
        "Deadlines": deadlines_visible_to(user).filter(is_archived=False).count(),
    }
    response = render(
        request,
        "cases/index.html",
        {
            "form": form,
            "page": page,
            "totals": totals,
            "can_create": has_capability(user, Action.CREATE_RECORDS),
            "can_view_audit": has_capability(user, Action.VIEW_AUDIT),
        },
        status=200 if page is not None else 400,
    )
    # Keep search terms out of referrers while preserving the origin for CSRF checks.
    response["Referrer-Policy"] = "origin"
    return response


@login_required
@require_safe
def detail(request, pk):
    user = request.user
    case = get_object_or_404(cases_visible_to(user).select_related("responsible_attorney"), pk=pk)
    if request.method == "GET":
        audit_change(request, "case.view", case)
    editable = case.status != Case.Status.CLOSED and not case.is_archived
    tasks = tasks_visible_to(user).filter(case=case)
    can_manage = can_manage_case(user, case)
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
            "team": case.memberships.filter(is_active=True)
            .select_related("user")
            .order_by("user__full_name", "pk"),
            "documents": documents_visible_to(user)
            .filter(case=case, state=Document.State.ACTIVE)
            .order_by("-uploaded_at", "-pk")[:10],
            "require_document_scan": settings.DOCUMENT_REQUIRE_SCAN,
            "deadlines": deadlines_visible_to(user)
            .filter(case=case)
            .select_related("responsible_user")
            .order_by("due_at", "pk"),
            # A Done task still offers the status link, because reopening it to
            # "To do" is a permitted transition (TASK-03).
            "task_rows": [
                (
                    task,
                    can_complete and not task.is_archived and task.assignee_id == user.pk,
                )
                for task in tasks.select_related("assignee").order_by("due_at", "pk")
            ],
            "now": timezone.now(),
            "can_edit": editable and case_allows(user, Action.EDIT_CASE, case),
            "can_link_clients": editable and can_manage,
            "can_manage_team": editable and can_manage,
            "can_change_status": not case.is_archived and can_manage,
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
    # Keep search terms out of referrers while preserving the origin for CSRF checks.
    response["Referrer-Policy"] = "origin"
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
    """LOG-02: filtered, paginated, newest-first review of audit events.

    Invalid filters, reversed or over-long date ranges and out-of-range pages are
    rejected with 400 and no results. The review itself is recorded as one
    ``audit_log.read`` event *after* the query has run, so it never appears in
    the page it describes and never triggers further logging.
    """
    if not has_capability(request.user, Action.VIEW_AUDIT):
        raise PermissionDenied
    form = AuditFilterForm(request.GET)
    page = None
    if form.is_valid():
        events = form.filter(audit_events_visible_to(request.user)).select_related("actor")
        paginator = Paginator(events, 50)
        number = form.cleaned_data["page"] or 1
        if number > paginator.num_pages:
            form.add_error("page", "This page does not exist.")
        else:
            page = paginator.page(number)
            page.object_list = list(page.object_list)
    if page is not None and request.method == "GET":
        audit_event(request, AuditAction.AUDIT_LOG_READ, Resource.AUDIT_LOG)
    return render(
        request,
        "cases/audit.html",
        {"form": form, "page": page},
        status=200 if page is not None else 400,
    )


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


def revision_response(
    request, form, title, record, action, case_id, *, fixed_changes=None, audit_fields=None
):
    context = {"case_record": record} if isinstance(record, Case) else {}
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
            return form_response(request, form, title, status=409, **context)
        # A caller may record a narrower set of names than it writes, for a
        # field that is not on the audit allowlist. The change still happens;
        # only the recorded field name is omitted.
        audit_change(request, action, record, changes if audit_fields is None else audit_fields)
        return redirect("cases:detail", pk=case_id)
    return form_response(request, form, title, **context)


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
        try:
            case = create_case(form, user)
        except ConcurrentEditError as exc:
            form.add_error(None, str(exc))
            return form_response(request, form, "Create case", status=409)
        audit_change(request, "case.create", case, ["clients", "members", "responsible_attorney"])
        return redirect("cases:detail", pk=case.pk)
    return form_response(request, form, "Create case")


def stale_case_form(form, revision):
    submitted = form.cleaned_data.get("revision")
    if submitted is not None and submitted != revision:
        form.add_error(None, "This case has changed. Reload it before saving.")
        return True
    return False


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_edit(request, pk):
    case = case_for_action(request, pk, Action.EDIT_CASE)
    revision = case.revision
    form = CaseEditForm(
        request.POST if request.method == "POST" else None,
        instance=case,
        editable_fields=editable_case_fields(request.user, case),
    )
    title = "Save case details"
    valid = form.is_valid()
    if request.method == "POST" and stale_case_form(form, revision):
        return form_response(request, form, title, status=409, case_record=case)
    require_editable(case)
    if valid:
        changes = {
            field: form.cleaned_data[field]
            for field in form.fields
            if field != "revision" and form.cleaned_data[field] != form.initial[field]
        }
        if changes:
            case.update_with_revision(revision, **changes)
            audit_change(request, "case.edit", case, changes)
        return redirect("cases:detail", pk=pk)
    return form_response(request, form, title, case_record=case)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_team(request, pk):
    case = case_for_action(request, pk, Action.EDIT_CASE)
    if not can_manage_case(request.user, case):
        raise PermissionDenied
    title = "Save case team"
    form = CaseTeamForm(request.POST if request.method == "POST" else None, case=case)
    valid = form.is_valid()
    if request.method == "POST" and stale_case_form(form, case.revision):
        return form_response(request, form, title, status=409, case_record=case)
    require_editable(case)
    if valid:
        try:
            fields = update_case_team(case, form.cleaned_data)
        except (ValidationError, ConcurrentEditError) as exc:
            form.add_error(None, str(exc) if isinstance(exc, ConcurrentEditError) else exc)
            return form_response(request, form, title, status=409, case_record=case)
        if fields:
            audit_change(request, "case.team", case, fields)
        return redirect("cases:detail", pk=pk)
    return form_response(request, form, title, case_record=case)


def reopening_attorney_choices(case, user):
    if case.status != Case.Status.CLOSED:
        return None
    attorneys = active_users_with_role(User.Role.ATTORNEY)
    assigned = attorneys.filter(memberships__case=case, memberships__is_active=True)
    if assigned.filter(pk=case.responsible_attorney_id).exists():
        return None
    return attorneys if user.role == User.Role.ADMINISTRATOR else assigned


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def case_status(request, pk):
    case = case_for_action(request, pk, Action.EDIT_CASE)
    if not can_manage_case(request.user, case) or case.is_archived:
        raise PermissionDenied
    reopening = case.status == Case.Status.CLOSED
    title = "Reopen case" if reopening else "Update case status"
    context = {"case_record": case}
    form = CaseStatusForm(
        request.POST if request.method == "POST" else None,
        case=case,
        targets=CASE_TRANSITIONS[case.status],
        replacements=reopening_attorney_choices(case, request.user),
    )
    valid = form.is_valid()
    if request.method == "POST" and stale_case_form(form, case.revision):
        return form_response(request, form, title, status=409, **context)
    if valid:
        status = form.cleaned_data["status"]
        if status == Case.Status.CLOSED:
            tasks, deadlines = map(list, outstanding_work(case))
            if tasks or deadlines:
                form.add_error(None, "Resolve these tasks and deadlines before closing the case.")
                return form_response(
                    request,
                    form,
                    title,
                    status=409,
                    blocking_tasks=tasks,
                    blocking_deadlines=deadlines,
                    **context,
                )
        try:
            fields = change_case_status(case, form.cleaned_data)
        except (ValidationError, ConcurrentEditError) as exc:
            form.add_error(None, str(exc) if isinstance(exc, ConcurrentEditError) else exc)
            return form_response(request, form, title, status=409, **context)
        action = {
            Case.Status.OPEN: "case.reopen" if reopening else "case.resume",
            Case.Status.IN_PROGRESS: "case.in_progress",
            Case.Status.ON_HOLD: "case.on_hold",
            Case.Status.CLOSED: "case.close",
        }[status]
        audit_change(request, action, case, fields)
        return redirect("cases:detail", pk=pk)
    return form_response(request, form, title, **context)


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
def document_index(request, pk):
    case = get_object_or_404(cases_visible_to(request.user), pk=pk)
    form = DocumentListForm(request.GET)
    page = None
    if form.is_valid():
        data = form.cleaned_data
        documents = documents_visible_to(request.user).filter(
            case=case, state=data["state"] or Document.State.ACTIVE
        )
        if data["category"]:
            documents = documents.filter(category=data["category"])
        paginator = Paginator(
            documents.select_related("uploaded_by", "archived_by").order_by("-uploaded_at", "-pk"),
            25,
        )
        number = data["page"] or 1
        if number > paginator.num_pages:
            form.add_error("page", "This page does not exist.")
        else:
            page = paginator.page(number)
            if request.method == "GET":
                audit_change(request, "document.list", case)
    editable = case.status != Case.Status.CLOSED and not case.is_archived
    return render(
        request,
        "cases/documents.html",
        {
            "case": case,
            "form": form,
            "page": page,
            "can_manage_documents": editable
            and case_allows(request.user, Action.MANAGE_DOCUMENTS, case),
            "can_archive_documents": editable and can_archive_documents(request.user, case),
            "require_document_scan": settings.DOCUMENT_REQUIRE_SCAN,
        },
        status=200 if page is not None else 400,
    )


@login_required
@require_http_methods(FORM_METHODS)
def document_upload(request, pk):
    # Validate/scan without holding a case lock, then authorize again before publishing.
    case = get_object_or_404(cases_visible_to(request.user), pk=pk)
    if not case_allows(request.user, Action.MANAGE_DOCUMENTS, case):
        raise PermissionDenied
    require_editable(case)
    posting = request.method == "POST"
    form = DocumentUploadForm(request.POST if posting else None, request.FILES if posting else None)
    title = "Upload document"
    context = {
        "case_record": case,
        "document_list_url": True,
        "description": "PDF, DOCX, UTF-8 TXT, JPG, or PNG. Maximum 10 MiB.",
    }
    if not posting:
        return form_response(request, form, title, **context)
    if form.is_valid():
        try:
            scanned_at = scan_upload(form.cleaned_data["file"])
            publish_document(request, pk, form, scanned_at=scanned_at)
        except ValidationError as exc:
            form.add_error("file", exc)
        except (ScanUnavailable, OSError):
            form.add_error("file", "The file could not be processed. Try again later.")
            audit_event(request, "document.upload", "document", result=AuditEvent.Result.FAILURE)
            return form_response(request, form, title, status=503, **context)
        else:
            return redirect("cases:documents", pk=pk)
    audit_event(request, "document.upload", "document", result=AuditEvent.Result.FAILURE)
    return form_response(request, form, title, **context)


@login_required
@require_safe
def document_download(request, pk, document_pk):
    documents = documents_visible_to(request.user)
    if settings.DOCUMENT_REQUIRE_SCAN:
        documents = documents.filter(malware_scanned_at__isnull=False)
    document = get_object_or_404(documents, case_id=pk, pk=document_pk)
    try:
        file = document.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404 from exc
    try:
        if request.method == "GET":
            audit_change(request, "document.download", document)
        name = document.original_filename
        response = FileResponse(
            file,
            as_attachment=True,
            filename=name if safe_filename(name) else "document",
            content_type="application/octet-stream",
        )
    except Exception:
        file.close()
        raise
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def document_edit(request, pk, document_pk):
    case = case_for_action(request, pk, Action.MANAGE_DOCUMENTS)
    document = get_object_or_404(documents_visible_to(request.user), case=case, pk=document_pk)
    require_editable(case)
    if document.state != Document.State.ACTIVE:
        raise PermissionDenied
    revision = document.revision
    posting = request.method == "POST"
    form = DocumentEditForm(
        request.POST if posting else None, request.FILES if posting else None, instance=document
    )
    title = "Save document details"
    context = {"case_record": case, "document_list_url": True}
    if form.is_valid():
        if form.cleaned_data["revision"] != revision:
            form.add_error(None, "This document has changed. Reload it before saving.")
            return form_response(request, form, title, status=409, **context)
        changes = {
            field: form.cleaned_data[field]
            for field in ("title", "category", "description")
            if form.cleaned_data[field] != form.initial[field]
        }
        if changes:
            document.update_with_revision(revision, **changes)
            audit_change(request, "document.edit", document, changes)
        return redirect("cases:documents", pk=pk)
    return form_response(request, form, title, **context)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def document_archive(request, pk, document_pk):
    case = case_for_action(request, pk, Action.MANAGE_DOCUMENTS)
    document = get_object_or_404(documents_visible_to(request.user), case=case, pk=document_pk)
    if not can_archive_documents(request.user, case):
        raise PermissionDenied
    require_editable(case)
    if document.state == Document.State.ARCHIVED:
        return HttpResponse("This document is already archived.", status=409)
    posting = request.method == "POST"
    form = DocumentArchiveForm(
        request.POST if posting else None,
        request.FILES if posting else None,
        initial={"revision": document.revision},
    )
    title = "Archive document"
    context = {
        "case_record": case,
        "document_list_url": True,
        "description": "Archive this document to keep its file and history in the Archived list.",
    }
    if form.is_valid():
        try:
            document.update_with_revision(
                form.cleaned_data["revision"],
                state=Document.State.ARCHIVED,
                archived_by=request.user,
                archived_at=timezone.now(),
                archive_reason=form.cleaned_data["archive_reason"],
            )
        except ConcurrentEditError as exc:
            form.add_error(None, str(exc))
            return form_response(request, form, title, status=409, **context)
        audit_change(request, "document.archive", document, ["state"])
        return redirect("cases:documents", pk=pk)
    return form_response(request, form, title, **context)


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


@login_required
@require_safe
def work_index(request):
    """Personal work list, defaulting to the signed-in user's own open tasks.

    Administrators and attorneys can widen the assignee filter to anyone they
    share a case with; the queryset still starts from `tasks_visible_to`, so
    widening it never reaches a case the viewer cannot see.
    """
    user = request.user
    tasks = tasks_visible_to(user).filter(is_archived=False)
    # The viewer is always a choice, so the dashboard's "my tasks" links work
    # even when they currently have no tasks.
    colleagues = User.objects.filter(
        Q(pk__in=tasks.values("assignee_id")) | Q(pk=user.pk)
    ).order_by("full_name", "pk")
    form = WorkFilterForm(request.GET or None, choices=colleagues)
    page = None
    if not request.GET:
        # No filters submitted: show my own work, which is the common case.
        tasks = tasks.filter(assignee=user)
        form = WorkFilterForm(choices=colleagues, initial={"assignee": user.pk})
        page = Paginator(tasks.order_by("due_at", "pk"), 25).get_page(1)
    elif form.is_valid():
        data = form.cleaned_data
        if data["assignee"]:
            tasks = tasks.filter(assignee=data["assignee"])
        if data["status"]:
            tasks = tasks.filter(status=data["status"])
        if data["priority"]:
            tasks = tasks.filter(priority=data["priority"])
        if data["overdue"] or data["window"] == "overdue":
            tasks = overdue_filter(tasks, Task)
        elif data["window"] == "upcoming":
            tasks = unfinished_upcoming_tasks(tasks)
        paginator = Paginator(tasks.select_related("case", "assignee").order_by("due_at", "pk"), 25)
        number = data["page"] or 1
        if number > paginator.num_pages:
            form.add_error("page", "This page does not exist.")
        else:
            page = paginator.page(number)
    if page is not None:
        audit_event(request, "task.list", "task")
    return render(
        request,
        "cases/work.html",
        {"form": form, "page": page, "now": timezone.now()},
    )


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def task_edit(request, pk, task_pk):
    """Update a task's own details, leaving its assignee and status untouched."""
    case = case_for_action(request, pk, Action.ASSIGN_TASKS)
    task = get_object_or_404(
        tasks_visible_to(request.user), case=case, pk=task_pk, is_archived=False
    )
    require_editable(case)
    form = TaskDetailsForm(
        request.POST if request.method == "POST" else None,
        initial={
            "revision": task.revision,
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_at": task.due_at,
        },
    )
    return revision_response(request, form, "Edit task", task, "task.edit", pk)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def task_status(request, pk, task_pk):
    """Move a task between statuses, recording completion time on `Done`.

    Only the assignee may change status, matching the permission matrix's
    "own tasks" rule. The transition is rechecked here because the form's
    choices are presentation, not authorization.
    """
    case = case_for_action(request, pk, Action.COMPLETE_TASK)
    task = get_object_or_404(
        tasks_visible_to(request.user), case=case, pk=task_pk, is_archived=False
    )
    require_editable(case)
    if not can_complete_task(request.user, task):
        raise PermissionDenied
    form = TaskStatusForm(
        request.POST if request.method == "POST" else None,
        current=task.status,
        initial={"revision": task.revision},
    )
    if form.is_valid():
        target = form.cleaned_data["status"]
        if not allows(TASK_TRANSITIONS, task.status, target):
            form.add_error("status", "This status change is not allowed.")
            return form_response(request, form, "Change task status")
        return revision_response(
            request,
            form,
            "Change task status",
            task,
            "task.status",
            pk,
            # Completion time is set on Done and cleared on reopen, so the
            # database's task_completion_matches_status constraint always holds.
            fixed_changes={
                "status": target,
                "completed_at": timezone.now() if target == Task.Status.DONE else None,
            },
        )
    return form_response(request, form, "Change task status")


@login_required
@require_safe
def deadline_index(request):
    """Authorized deadline list with overdue and upcoming windows (DATE-02)."""
    user = request.user
    deadlines = deadlines_visible_to(user).filter(is_archived=False)
    colleagues = User.objects.filter(pk__in=deadlines.values("responsible_user_id")).order_by(
        "full_name", "pk"
    )
    form = DeadlineFilterForm(request.GET or None, choices=colleagues)
    page = None
    if not request.GET:
        form = DeadlineFilterForm(choices=colleagues)
        page = Paginator(deadlines.order_by("due_at", "pk"), 25).get_page(1)
    elif form.is_valid():
        data = form.cleaned_data
        if data["responsible_user"]:
            deadlines = deadlines.filter(responsible_user=data["responsible_user"])
        if data["status"]:
            deadlines = deadlines.filter(status=data["status"])
        if data["type"]:
            deadlines = deadlines.filter(type=data["type"])
        if data["window"] == "overdue":
            deadlines = overdue_filter(deadlines, Deadline)
        elif data["window"] == "upcoming":
            deadlines = pending_upcoming_deadlines(deadlines)
        paginator = Paginator(
            deadlines.select_related("case", "responsible_user").order_by("due_at", "pk"), 25
        )
        number = data["page"] or 1
        if number > paginator.num_pages:
            form.add_error("page", "This page does not exist.")
        else:
            page = paginator.page(number)
    if page is not None:
        audit_event(request, "deadline.list", "deadline")
    return render(
        request,
        "cases/deadlines.html",
        {"form": form, "page": page, "now": timezone.now()},
    )


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def deadline_create(request, pk):
    """Record a new pending deadline against an editable case (DATE-01)."""
    case = case_for_action(request, pk, Action.ASSIGN_TASKS)
    require_editable(case)
    form = DeadlineForm(request.POST if request.method == "POST" else None, case=case)
    if form.is_valid():
        deadline = form.save(commit=False)
        lock_assignee_membership(case, deadline.responsible_user)
        deadline.case = case
        deadline.created_by = request.user
        deadline.save()
        audit_change(request, "deadline.create", deadline, ["title", "type", "due_at"])
        return redirect("cases:detail", pk=pk)
    return form_response(request, form, "Add deadline")


def deadline_for_action(request, pk, deadline_pk, action):
    """Fetch an editable deadline through the viewer's own scope, or 404."""
    case = case_for_action(request, pk, action)
    deadline = get_object_or_404(
        deadlines_visible_to(request.user), case=case, pk=deadline_pk, is_archived=False
    )
    require_editable(case)
    return case, deadline


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def deadline_edit(request, pk, deadline_pk):
    """Revise a pending deadline's details, including moving its date."""
    case, deadline = deadline_for_action(request, pk, deadline_pk, Action.ASSIGN_TASKS)
    form = DeadlineDetailsForm(
        request.POST if request.method == "POST" else None,
        case=case,
        initial={
            "revision": deadline.revision,
            "title": deadline.title,
            "type": deadline.type,
            "due_at": deadline.due_at,
            "responsible_user": deadline.responsible_user_id,
            "notes": deadline.notes,
        },
    )
    if form.is_valid():
        lock_assignee_membership(case, form.cleaned_data["responsible_user"])
    return revision_response(request, form, "Edit deadline", deadline, "deadline.edit", pk)


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def deadline_resolve(request, pk, deadline_pk):
    """Complete or cancel a deadline, recording actor, instant and reason."""
    case, deadline = deadline_for_action(request, pk, deadline_pk, Action.ASSIGN_TASKS)
    if deadline.status != Deadline.Status.PENDING:
        return HttpResponse("This deadline is already resolved.", status=409)
    form = DeadlineResolutionForm(
        request.POST if request.method == "POST" else None,
        initial={"revision": deadline.revision},
    )
    if form.is_valid():
        target = form.cleaned_data["status"]
        if not allows(DEADLINE_TRANSITIONS, deadline.status, target):
            form.add_error("status", "This status change is not allowed.")
            return form_response(request, form, "Resolve deadline")
        return revision_response(
            request,
            form,
            "Resolve deadline",
            deadline,
            "deadline.resolve",
            pk,
            # completion_notes is not an allowlisted audit field name; the reason
            # itself lives on the deadline record, where DATE-01 wants it.
            audit_fields=["status", "completed_at", "completed_by"],
            fixed_changes={
                "status": target,
                "completed_at": timezone.now(),
                "completed_by": request.user,
                "completion_notes": form.cleaned_data["completion_notes"],
            },
        )
    return form_response(request, form, "Resolve deadline")


@login_required
@require_http_methods(FORM_METHODS)
@transaction.atomic
def deadline_reopen(request, pk, deadline_pk):
    """Return a resolved deadline to pending, clearing its completion details."""
    case, deadline = deadline_for_action(request, pk, deadline_pk, Action.ASSIGN_TASKS)
    if deadline.status == Deadline.Status.PENDING:
        return HttpResponse("This deadline is already pending.", status=409)
    form = RevisionForm(
        request.POST if request.method == "POST" else None, initial={"revision": deadline.revision}
    )
    return revision_response(
        request,
        form,
        "Reopen deadline",
        deadline,
        "deadline.reopen",
        pk,
        # completion_notes is not an allowlisted audit field name; the reason
        # itself lives on the deadline record, where DATE-01 wants it.
        audit_fields=["status", "completed_at", "completed_by"],
        # Clearing all three keeps deadline_completion_consistent satisfied.
        fixed_changes={
            "status": Deadline.Status.PENDING,
            "completed_at": None,
            "completed_by": None,
            "completion_notes": "",
        },
    )
