"""Low-cardinality dashboard metrics and structured request completion logs."""

import logging
import os
from time import perf_counter

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_safe
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)

logger = logging.getLogger("lexflow.requests")
REGISTRY = CollectorRegistry()
REQUESTS = Counter(
    "lexflow_dashboard_requests_total",
    "Completed GET requests to the dashboard entry route.",
    ["status"],
    registry=REGISTRY,
)
LATENCY = Histogram(
    "lexflow_dashboard_request_duration_seconds",
    "Wall-clock server duration for GET requests to the dashboard entry route.",
    ["status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    registry=REGISTRY,
)


@require_safe
def health(request):
    # Liveness only: no dependency calls, configuration details, or case data.
    return JsonResponse({"status": "ok"})


@require_safe
def metrics(request):
    registry = REGISTRY
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)


class RequestMetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = perf_counter()
        status = 500
        try:
            response = self.get_response(request)
            status = response.status_code
            return response
        finally:
            duration = max(0, perf_counter() - started)
            if request.path_info == "/dashboard/" and request.method == "GET":
                REQUESTS.labels(status=str(status)).inc()
                LATENCY.labels(status=str(status)).observe(duration)
            match = getattr(request, "resolver_match", None)
            logger.info(
                "request.completed",
                extra={
                    "method": request.method,
                    "route": match.view_name if match else "unmatched",
                    "status": status,
                    "duration_seconds": round(duration, 6),
                },
            )
