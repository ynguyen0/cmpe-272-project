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
    return Case.objects.filter(memberships__user=user, memberships__is_active=True).distinct()


def clients_visible_to(user):
    if not user.is_authenticated or not user.is_active:
        return Client.objects.none()
    if user.is_administrator:
        return Client.objects.all()
    return Client.objects.filter(
        Q(case_links__case__in=cases_visible_to(user), case_links__is_active=True)
        | Q(case_links__isnull=True, created_by=user)
    ).distinct()
