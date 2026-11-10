from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .policies import cases_visible_to


@login_required
def index(request):
    return render(request, "cases/index.html", {"cases": cases_visible_to(request.user)})


@login_required
def detail(request, pk):
    case = get_object_or_404(cases_visible_to(request.user), pk=pk)
    return render(request, "cases/detail.html", {"case": case})
