from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


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


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMINISTRATOR = "Administrator"
        ATTORNEY = "Attorney"
        STAFF = "Staff"

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    first_name = None
    last_name = None

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]
    objects = UserManager()

    class Meta:
        constraints = [
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

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name

    def __str__(self):
        return self.full_name
