import atexit
import shutil
import tempfile

from .base import *

DEBUG = False
ALLOW_DEMO_DATA = True
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "[::1]"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# Each test process gets isolated files, removed on exit; never use development uploads.
PRIVATE_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="lexflow-tests-"))
atexit.register(shutil.rmtree, PRIVATE_MEDIA_ROOT, ignore_errors=True)
STORAGES = {
    **STORAGES,
    "default": {
        "BACKEND": "documents.storage.PrivateFileSystemStorage",
        "OPTIONS": {"location": PRIVATE_MEDIA_ROOT},
    },
}
