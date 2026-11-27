from django.shortcuts import redirect, render
from django.views.decorators.http import require_safe


@require_safe
def home(request):
    if request.user.is_authenticated:
        return redirect("cases:dashboard")
    return render(request, "landing.html")
