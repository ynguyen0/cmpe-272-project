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

## Known gap

`accounts.security.audit_account` writes `AuditEvent` rows directly and sets its
own `request.audit_correlation_id`, so account events do not share the
middleware's `request.correlation_id`, and they skip the allowlist, pattern and
transaction checks above. Pointing that helper at `record_event()` would unify
both. Raised for team review rather than changed unilaterally.
