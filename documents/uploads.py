"""Bound multipart uploads before validation or storage."""

from html import unescape

from django.core.files.uploadhandler import FileUploadHandler, TemporaryFileUploadHandler
from django.http.multipartparser import MultiPartParser, MultiPartParserError

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_DOCUMENT_BYTES + 64 * 1024


def safe_filename(name):
    return (
        0 < len(name) <= 255
        and name not in {".", ".."}
        and name == name.strip()
        and name.isprintable()
        and not any(char in name for char in "/\\:")
    )


class DocumentMultipartParser(MultiPartParser):
    def sanitize_file_name(self, file_name):
        # Check the name before Django strips path components and control characters.
        name = unescape(file_name)
        if not safe_filename(name):
            raise MultiPartParserError("Invalid upload filename.")
        return name


class BoundedTemporaryUpload(TemporaryFileUploadHandler):
    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > MAX_DOCUMENT_BYTES:
            raise MultiPartParserError("The file exceeds 10 MiB.")
        return super().receive_data_chunk(raw_data, start)


class DocumentUploadHandler(FileUploadHandler):
    def handle_raw_input(self, input_data, meta, content_length, boundary, encoding=None):
        if content_length > MAX_MULTIPART_BYTES:
            raise MultiPartParserError("The upload request is too large.")
        handler = BoundedTemporaryUpload(self.request)
        try:
            return DocumentMultipartParser(meta, input_data, [handler], encoding).parse()
        except Exception:
            # Django's parser closes completed files. Close the in-flight file as well.
            handler.upload_interrupted()
            raise
