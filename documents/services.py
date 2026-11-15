"""Publish validated files and compensate for filesystem writes on rollback."""

import logging

from django.db import DatabaseError, connection, transaction

from cases.policies import Action
from cases.services import audit_change, case_for_action, require_editable

from .models import Document, private_upload_path

logger = logging.getLogger(__name__)
STORAGE_LOCK = 7_102_339_511


def lock_private_storage(*, shared=False):
    with connection.cursor() as cursor:
        if shared:
            cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [STORAGE_LOCK])
        else:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [STORAGE_LOCK])


def publish_document(request, case_id, form, *, scanned_at):
    document = form.save(commit=False)
    upload = form.cleaned_data["file"]
    storage = document.file.storage
    key = None
    try:
        with transaction.atomic(durable=True):
            case = case_for_action(request, case_id, Action.MANAGE_DOCUMENTS)
            require_editable(case)
            lock_private_storage(shared=True)
            document.case = case
            document.uploaded_by = request.user
            document.original_filename = upload.name
            document.size = upload.size
            document.media_type = form.detected_type
            document.malware_scanned_at = scanned_at
            candidate = private_upload_path(document, upload.name)
            while storage.exists(candidate):
                candidate = private_upload_path(document, upload.name)
            key = candidate
            key = storage.save(key, upload)
            document.file = key
            document.save()
            audit_change(request, "document.upload", document)
    except Exception:
        if key is not None:
            try:
                # A dropped connection can leave the outcome of a commit unknown.
                if not Document.objects.filter(file=key).exists():
                    storage.delete(key)
            except (DatabaseError, OSError):
                logger.error("Document upload cleanup deferred. Run the storage cleanup command.")
        raise
    return document
