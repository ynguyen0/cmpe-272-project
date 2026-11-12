from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.http import require_safe


@require_safe
def wireframe(request):
    if not settings.ALLOW_DEMO_DATA:
        raise Http404
    return render(request, "wireframe.html")
