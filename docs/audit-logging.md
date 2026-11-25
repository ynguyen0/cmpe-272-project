# Audit logging: how to record an event

Owner: Member A (LOG-01/LOG-02). This is the supported way to write an
`AuditEvent`. Permissions are a separate concern — use `cases.policies`.

## Calling it

```python
from django.db import transaction

from audit.models import AuditEvent
from audit.services import Action, Resource, record_event

with transaction.atomic():
    case.update_with_revision(expected_revision, status="On hold")
    record_event(
        actor=request.user,  # None when nobody is signed in
        action=Action.CASE_STATUS_CHANGED,
        resource_type=Resource.CASE,
        resource_id=case.pk,  # a generated ID, never an email or free text
        result=AuditEvent.Result.SUCCESS,  # SUCCESS | FAILURE | DENIED
        changed_fields=["status"],  # names only; omit for reads
        require_atomic=True,  # at every mutation call site
    )
```

Call it inside the same `transaction.atomic()` block as the change it describes:
the event then joins that transaction, so a rolled-back mutation discards its
event too (rule G5). `require_atomic=True` makes the helper refuse to run
outside a transaction, turning a silent accountability gap into a loud failure.

`correlation_id` fills itself in from `audit.middleware`, so leave it alone —
every event from one request shares one ID.

## What it refuses

1. **Values.** `changed_fields` accepts only names from
   `AuditEvent.CHANGE_FIELDS`, at most 20. `"password"`, `"notes"` or
   `"email=someone@example.test"` raise `ValueError` and write nothing. No
   parameter accepts a value, so client text, file bytes, passwords and tokens
   cannot reach the log even by accident.
2. **Forged structure.** Actions must look like `resource.verb`; resource types
   are bare lowercase words; resource IDs allow only generated-identifier
   characters. Newlines and spaces are rejected.
3. **Rewriting history.** A PostgreSQL trigger rejects UPDATE and DELETE on
   `audit_auditevent`, so recorded events cannot be altered — including by tests.

## What to log

Rule G5 asks for successful reads, searches and downloads, all mutations,
authentication events, and authorization denials. The project abstract names
"creating, editing, viewing, or deleting", so **reads count**: a list or detail
view needs an event too, not only writes.

## Adding your own actions

Add a constant to `Action` in `audit/services.py` rather than passing a string,
so the LOG-02 action filter stays meaningful. Follow `<resource>.<verb>` with a
verb from: `read`, `searched`, `created`, `updated`, `status_changed`,
`archived`, `uploaded`, `downloaded`, `assigned`, `linked`, `unlinked`.

A genuinely new changed-field name must be added to `AuditEvent.CHANGE_FIELDS`
**and** to the database check constraint in a migration. The constraint is the
real enforcement; the Python check exists to give a readable error first.

## Account events

`accounts.security.audit_account` is a thin wrapper over `record_event()` with
`resource_type="user"`, so authentication and account-administration events get
the same allowlist, pattern checks and per-request correlation ID as every other
event. Recorded: sign-in success, failure and throttling; sign-out; idle or
absolute session expiry; revocation of a deactivated account's session
(`auth.session_revoked`); password change, reset request and reset; account
creation, role change, deactivation and reactivation. A reset request has no
target, because naming the matching account would reveal whether an email is
registered.

## Access denials

`audit.middleware.AccessDenialAuditMiddleware` records refused requests as
`access.denied` with result `denied`, the actor (or none), and the record the
URL asked for. It works in `process_exception`, which Django calls after the
view's `transaction.atomic()` block has rolled back, so the denial is written
in its own transaction and survives the rollback of whatever the request tried
to change.

* `PermissionDenied` is always recorded.
* `Http404` is recorded only when the requested record exists. Scoped lookups
  return 404 for records outside the caller's assignments, so the caller cannot
  tell "hidden" from "missing"; the event is visible only to auditors.
* A view that records its own, more specific denial (the account screens do,
  through `audit_account(..., DENIED)`) is not recorded a second time.

Feature code therefore just raises `PermissionDenied` or 404s as usual; it does
not need to log denials itself.

## When an audit write fails

The rule is **no unaudited change, and no denial turned into access**:

| Event kind | If the audit write fails |
| --- | --- |
| Mutation (create, edit, status, assignment, archive, upload) | The event is in the same transaction, so the exception rolls the change back and the request fails with a server error. The change is not saved. |
| Read, search, list or download | The event is written before the response is built, so the request fails and the data is not served. |
| Authentication and account events | The request fails with a server error; account changes roll back with their event. |
| Access denial | The request is still refused exactly as before. The failure is reported to the `lexflow.audit` logger with only the exception type, never the request data. |

Operators should alert on `lexflow.audit` errors and on server errors in general.

## Reviewing the log (LOG-02)

Administrators with the `view_organization_audit` grant open **Audit records**
(`/audit/`). Events are newest first (time, then ID), 50 per page, and can be
filtered by actor, action, record type, record ID and an inclusive UTC date
range. The default range is the last 7 days and a range may cover at most 31
days. Reversed or over-long ranges, malformed dates or IDs, unknown actions or
actors, unexpected parameters and out-of-range pages are rejected with 400 and
no results. Each successful review records one `audit_log.read` event after the
query runs, so it never appears in the page it describes and never causes
further logging. Refused reviews are recorded as `access.denied`.

## Limits of tamper resistance

Application users, including administrators, cannot change or delete audit
events: there is no edit or delete screen, and a PostgreSQL trigger rejects
`UPDATE` and `DELETE` on `audit_auditevent`. This is **not** protection against
someone with database administrator rights, who can disable the trigger, edit
rows or drop the table. Stronger tamper resistance (shipping events to a
separate write-once store, hash-chaining rows, or restricting the application's
database role) is a later operational enhancement and is out of scope for
release 1.


## Validation and conflict failures

Authenticated case-domain GET/POST responses with status 400 or 409 also record
one `validation.failed` event with result `failure`. This includes invalid forms,
invalid list/audit filters and stale writes. The event is written after the view's
transaction finishes, using only the actor and URL resource context; submitted
values, query strings, completion notes and error messages are never copied into
the event. A create URL may identify the parent case because no child record was
created. Account screens retain their existing explicit failure capture. Audit
storage failure fails the request rather than silently accepting missing evidence.

`ValidationAuditTests` in [release quality tests](../tests/test_release_quality.py)
verify invalid deadline, stale task and invalid audit-filter outcomes, redaction,
and unchanged business data.
