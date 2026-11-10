from django.core.files.storage import FileSystemStorage


class PrivateFileSystemStorage(FileSystemStorage):
    """Files have no public URL. A future download view must authorize each request."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("file_permissions_mode", 0o600)
        kwargs.setdefault("directory_permissions_mode", 0o700)
        super().__init__(*args, **kwargs)

    def url(self, name):
        raise ValueError("Private files have no public URL.")
