from django.core.exceptions import ImproperlyConfigured

from .base import *

if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured(
        "Deployment requires a strong, unique DJANGO_SECRET_KEY (50+ chars)."
    )
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS for deployment.")
CSRF_TRUSTED_ORIGINS = csv_env("DJANGO_CSRF_TRUSTED_ORIGINS")
if not CSRF_TRUSTED_ORIGINS or any(
    not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS
):
    raise ImproperlyConfigured("Set HTTPS DJANGO_CSRF_TRUSTED_ORIGINS for deployment.")
required("DJANGO_PRIVATE_MEDIA_ROOT")
if not PRIVATE_MEDIA_ROOT.is_absolute():
    raise ImproperlyConfigured("DJANGO_PRIVATE_MEDIA_ROOT must be an absolute private path.")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# Configure forwarded-proto trust only after a trusted proxy strips inbound spoofed headers.
# Do not enable SECURE_PROXY_SSL_HEADER blindly.
