from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils.crypto import salted_hmac

from config.models import RevisionedModel, nonblank_check, revision_checks


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).strip().lower(), **extra_fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMINISTRATOR)
        if (
            extra_fields.get("is_staff") is not True
            or extra_fields.get("is_superuser") is not True
            or extra_fields.get("role") != User.Role.ADMINISTRATOR
        ):
            raise ValueError("Superusers must be administrators with both Django admin flags.")
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser, RevisionedModel):
    class Role(models.TextChoices):
        ADMINISTRATOR = "Administrator"
        ATTORNEY = "Attorney"
        STAFF = "Staff"

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    session_version = models.PositiveIntegerField(default=0, editable=False)
    first_name = None
    last_name = None

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta:
        constraints = [
            *revision_checks(),
            nonblank_check("email"),
            nonblank_check("full_name"),
            models.UniqueConstraint(Lower("email"), name="user_email_case_insensitive_unique"),
            models.CheckConstraint(
                condition=models.Q(role__in=["Administrator", "Attorney", "Staff"]),
                name="user_valid_role",
            ),
        ]

    @property
    def is_administrator(self):
        return self.is_active and self.role == self.Role.ADMINISTRATOR

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()

    def _get_session_auth_hash(self, secret=None):
        if not self.session_version:
            return super()._get_session_auth_hash(secret)
        return salted_hmac(
            "accounts.User.session_auth_hash",
            f"{self.password}:{self.session_version}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name

    def __str__(self):
        return self.full_name


class LoginThrottle(models.Model):
    identity = models.CharField(max_length=64, primary_key=True)
    failures = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField(db_index=True)
