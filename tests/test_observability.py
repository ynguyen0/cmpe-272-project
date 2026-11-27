"""Health, measurable dashboard SLO, JSON correlation, and dependency deadlines."""

import json
import logging
import os
import subprocess
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from django.conf import settings
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from audit.middleware import AuditCorrelationMiddleware
from config import observability
from config.logging import JSONFormatter
from config.request_context import correlation_id
from documents.management.commands.backup_lexflow import Command


class ObservabilityTests(SimpleTestCase):
    def test_health_and_metrics_are_public_and_do_not_query_dependencies(self):
        self.client.cookies[settings.SESSION_COOKIE_NAME] = "a" * 32
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        UUID(response["X-Request-ID"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post("/health").status_code, 405)
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        self.assertContains(response, "lexflow_dashboard_requests_total")
        self.assertContains(response, "lexflow_dashboard_request_duration_seconds")
        self.assertEqual(self.client.post("/metrics").status_code, 405)

    def sample(self, metric, **labels):
        return observability.REGISTRY.get_sample_value(metric, labels) or 0

    def test_dashboard_counter_and_histogram_include_errors_and_one_second_bucket(self):
        request = RequestFactory().get("/dashboard/")
        for status in (200, 302, 500):
            with self.subTest(status=status):
                labels = {"status": str(status)}
                before = self.sample("lexflow_dashboard_requests_total", **labels)
                bucket = self.sample(
                    "lexflow_dashboard_request_duration_seconds_bucket", **labels, le="1.0"
                )
                count = self.sample("lexflow_dashboard_request_duration_seconds_count", **labels)
                total = self.sample("lexflow_dashboard_request_duration_seconds_sum", **labels)
                middleware = observability.RequestMetricsMiddleware(
                    lambda request, code=status: HttpResponse(status=code)
                )
                with patch("config.observability.perf_counter", side_effect=[10, 10.75]):
                    self.assertEqual(middleware(request).status_code, status)
                self.assertEqual(
                    self.sample("lexflow_dashboard_requests_total", **labels), before + 1
                )
                self.assertEqual(
                    self.sample("lexflow_dashboard_request_duration_seconds_count", **labels),
                    count + 1,
                )
                self.assertEqual(
                    self.sample(
                        "lexflow_dashboard_request_duration_seconds_bucket", **labels, le="1.0"
                    ),
                    bucket + 1,
                )
                self.assertAlmostEqual(
                    self.sample("lexflow_dashboard_request_duration_seconds_sum", **labels),
                    total + 0.75,
                )
        before = self.sample("lexflow_dashboard_requests_total", status="200")
        middleware(RequestFactory().get("/health"))
        middleware(RequestFactory().get("/"))
        middleware(RequestFactory().post("/dashboard/"))
        self.assertEqual(self.sample("lexflow_dashboard_requests_total", status="200"), before)

    def test_json_request_logs_share_response_id_and_reset_context(self):
        previous = correlation_id.get()
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        logger = logging.getLogger("lexflow.requests")
        logger.addHandler(handler)
        try:
            first = self.client.get("/dashboard/?q=confidential", HTTP_X_REQUEST_ID="forged")
            second = self.client.get("/health")
        finally:
            logger.removeHandler(handler)
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["request_id"], first["X-Request-ID"])
        self.assertEqual(records[1]["request_id"], second["X-Request-ID"])
        self.assertNotEqual(first["X-Request-ID"], second["X-Request-ID"])
        self.assertNotEqual(first["X-Request-ID"], "forged")
        self.assertNotIn("confidential", stream.getvalue())
        self.assertEqual(records[0]["route"], "cases:dashboard")
        self.assertEqual(correlation_id.get(), previous)

    def test_exceptions_are_counted_and_context_is_reset(self):
        previous = correlation_id.get()

        def failure(request):
            raise RuntimeError("Synthetic dependency failure")

        before = self.sample("lexflow_dashboard_requests_total", status="500")
        middleware = AuditCorrelationMiddleware(observability.RequestMetricsMiddleware(failure))
        with self.assertRaises(RuntimeError):
            middleware(RequestFactory().get("/dashboard/"))
        self.assertEqual(self.sample("lexflow_dashboard_requests_total", status="500"), before + 1)
        self.assertEqual(correlation_id.get(), previous)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_security_redirects_also_receive_a_request_id(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 301)
        UUID(response["X-Request-ID"])

    def test_formatter_escapes_lines_and_redacts_tokens_and_queries(self):
        record = logging.LogRecord(
            "django.request",
            logging.ERROR,
            "",
            0,
            "GET /accounts/reset/user/private-token/\nGET /search/?q=private-client",
            (),
            None,
        )
        rendered = JSONFormatter().format(record)
        self.assertEqual(len(rendered.splitlines()), 1)
        value = json.loads(rendered)
        self.assertIn("request_id", value)
        self.assertNotIn("private-token", rendered)
        self.assertNotIn("private-client", rendered)
        self.assertNotIn("request", value)

    def test_backup_timeout_fails_without_leaving_a_published_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("documents.management.commands.backup_lexflow.transaction.atomic"),
                patch(
                    "documents.management.commands.backup_lexflow.connection",
                    settings_dict=settings.DATABASES["default"],
                ),
                patch("documents.management.commands.backup_lexflow.lock_private_storage"),
                patch(
                    "documents.management.commands.backup_lexflow.subprocess.run",
                    side_effect=subprocess.TimeoutExpired("pg_dump", 120),
                ) as run,
            ):
                with self.assertRaisesMessage(CommandError, "Backup failed"):
                    Command().handle(destination=Path(directory))
                self.assertEqual(run.call_args.kwargs["timeout"], 120)
                self.assertEqual(run.call_args.kwargs["env"]["PGCONNECT_TIMEOUT"], "5")
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_metrics_aggregate_across_worker_processes(self):
        script = """
from types import SimpleNamespace
from config.observability import REQUESTS, LATENCY, metrics
REQUESTS.labels(status='200').inc()
LATENCY.labels(status='200').observe(0.2)
print(metrics(SimpleNamespace(method='GET')).content.decode())
"""
        with tempfile.TemporaryDirectory() as directory:
            env = {
                **os.environ,
                "PROMETHEUS_MULTIPROC_DIR": directory,
                "DJANGO_SETTINGS_MODULE": "config.settings.test",
            }
            for _ in range(2):
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('lexflow_dashboard_requests_total{status="200"} 2.0', result.stdout)
        self.assertIn(
            'lexflow_dashboard_request_duration_seconds_count{status="200"} 2.0', result.stdout
        )


class DependencyTimeoutTests(TestCase):
    def test_live_database_session_has_query_and_lock_deadlines(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            self.assertEqual(cursor.fetchone()[0], "10s")
            cursor.execute("SHOW lock_timeout")
            self.assertEqual(cursor.fetchone()[0], "3s")
        self.assertEqual(settings.EMAIL_TIMEOUT, 10)
