from django.conf import settings
from django.db import models


class Client(models.Model):
    class Type(models.TextChoices):
        INDIVIDUAL = "Individual"
        ORGANIZATION = "Organization"

    name = models.CharField(max_length=150)
    type = models.CharField(max_length=20, choices=Type.choices)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=500, blank=True)
    notes = models.CharField(max_length=2000, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
