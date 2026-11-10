"""All record selectors must start with these scopes, not a role-only check.

Mutation permissions and lifecycle transitions belong in transactional services as
their backlog stories are implemented. These selectors grant read access only.
"""

from django.db.models import Q

from clients.models import Client

from .models import Case


def cases_visible_to(user):
    if not user.is_authenticated or not user.is_active:
        return Case.objects.none()
    if user.is_administrator:
        return Case.objects.all()
    return Case.objects.filter(members=user).distinct()


def clients_visible_to(user):
    if not user.is_authenticated or not user.is_active:
        return Client.objects.none()
    if user.is_administrator:
        return Client.objects.all()
    return Client.objects.filter(
        Q(cases__in=cases_visible_to(user)) | Q(cases__isnull=True, created_by=user)
    ).distinct()
