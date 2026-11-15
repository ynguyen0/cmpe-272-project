"""Search and deduplication over an already authorized client queryset."""

import re
from difflib import SequenceMatcher

from django.db.models import F, Func, Q, Value

PHONE_INPUT = re.compile(r"\+?[0-9 ()-]+")


def phone_digits(value):
    return re.sub(r"[^0-9]", "", value)


def search_clients(clients, query):
    if not query:
        return clients
    matches = Q(name__icontains=query) | Q(email__icontains=query)
    digits = phone_digits(query) if PHONE_INPUT.fullmatch(query) else ""
    if digits:
        if query.isascii() and query.isdecimal() and len(query) <= 19:
            pk = int(query)
            if 0 < pk <= 2**63 - 1:
                matches |= Q(pk=pk)
        clients = clients.alias(
            phone_digits=Func(
                F("phone"), Value("[^0-9]"), Value(""), Value("g"), function="regexp_replace"
            )
        )
        matches |= Q(phone_digits__contains=digits)
    return clients.filter(matches)


def name_key(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def possible_duplicates(clients, data, *, exclude_pk=None):
    name = name_key(data["name"])
    email = data["email"]
    phone = phone_digits(data["phone"])
    matches = []
    for client in (
        clients.exclude(pk=exclude_pk)
        .only("name", "email", "phone", "status")
        .order_by("name", "pk")
        .iterator()
    ):
        candidate = name_key(client.name)
        if (
            (email and email == client.email.strip().lower())
            or (phone and phone == phone_digits(client.phone))
            or (
                name
                and candidate
                and (
                    name == candidate
                    or (
                        min(len(name), len(candidate)) >= 5
                        and SequenceMatcher(None, name, candidate).ratio() >= 0.85
                    )
                )
            )
        ):
            matches.append(client)
            if len(matches) == 5:
                break
    return matches
