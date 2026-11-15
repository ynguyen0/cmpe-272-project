from django.core.files.storage import FileSystemStorage


class PrivateFileSystemStorage(FileSystemStorage):
    """Private files are available only through an authorized download."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("file_permissions_mode", 0o600)
        kwargs.setdefault("directory_permissions_mode", 0o700)
        super().__init__(*args, **kwargs)

    def url(self, name):
        raise ValueError("Private files have no public URL.")
