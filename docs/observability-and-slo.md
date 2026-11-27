# Observability, demo SLO, and outgoing-call timeouts

Implemented 2026-11-26. This defines a target and its measurement; it does not
claim that a production service has met the target for 30 days.

## Health and metrics

- `GET /health` (also HEAD) returns HTTP 200 and `{"status":"ok"}`. It is a
  dependency-free liveness check, not a database readiness check. Probes skip
  session lookup even with a stale session cookie. Deployment still requires HTTPS.
- `GET /metrics` exposes Prometheus text with no case IDs, user IDs, filenames,
  search terms, or request IDs in labels. Both endpoints are public read-only
  operational endpoints; the deployment proxy should limit metrics scraping to
  the monitoring network. Neither endpoint loads the session database.
- `lexflow_dashboard_requests_total{status="200"}` counts completed **GET `/`**
  requests, including failures and redirects under their actual status codes.
- `lexflow_dashboard_request_duration_seconds{status="200"}` records server
  wall-clock time in cumulative histogram buckets, plus `_count` and `_sum`.
  Buckets include 1 second to match the SLO. Timing includes authentication,
  dashboard queries, rendering, and inner middleware; it excludes socket transfer,
  browser rendering, and the small outer correlation-header overhead.
- Health, metrics, other routes, and non-GET requests do not inflate dashboard
  metrics. All requests still generate completion logs. Counts reset on service
  restart, so use Prometheus `increase`/`rate`, not raw subtraction across restarts.

For one process, the default registry is sufficient. For multiple Gunicorn
workers, set `PROMETHEUS_MULTIPROC_DIR` **before starting Python**, pointing to a
private directory shared by workers of that service instance. Start each new
service instance with an empty directory; do not delete files while it is running.
Workers write shared metric files; `/metrics` uses `MultiProcessCollector` to
aggregate them. Use the included Gunicorn configuration for JSON diagnostics and
worker cleanup:

```sh
# Supply the deployment environment described in README first.
# Use a fresh, private metrics directory for this service start.
export PROMETHEUS_MULTIPROC_DIR="$(mktemp -d /tmp/lexflow-metrics.XXXXXX)"
uv run gunicorn config.wsgi:application --config python:config.gunicorn --workers 2 --bind 127.0.0.1:8000
```

Remove that instance's metrics directory after all its workers stop. Each replica
needs its own directory and scrape target; aggregate replicas in Prometheus.
See the [official multiprocess requirements](https://prometheus.github.io/client_python/multiprocess/).

## JSON logs and request correlation

Django and application logging use one JSON object per physical console line:

```json
{"timestamp":"2026-11-26T12:00:00+00:00","level":"INFO","logger":"lexflow.requests","request_id":"a1234567-1234-4567-8901-123456789abc","message":"request.completed","method":"GET","route":"cases:dashboard","status":200,"duration_seconds":0.12}
```

The middleware generates the ID, binds it to the existing audit context, and
returns it in `X-Request-ID`. Caller-supplied IDs are not trusted. Context resets
in `finally`, including after errors, preventing reuse across requests. Correlation
wraps the security middleware, so HTTPS redirects have IDs too. Logs outside an
HTTP request have `request_id: "-"` unless an audit/command context is bound.

Completion records use route names rather than raw paths or query strings.
The JSON formatter preserves URL-token/query redaction for Django diagnostics,
escapes embedded newlines, and does not serialize request objects or arbitrary
extra fields. Exception diagnostics include the exception type and stack frames,
without exception values or locals. Existing database audit events remain the
transactional accountability record.

Application completion logs replace runserver/Gunicorn's duplicate raw-URL access
logs. The supplied Gunicorn configuration also formats its startup/error messages
as JSON. Reverse-proxy/access logs are managed separately and must use the returned
request ID, redact sensitive URLs, and use JSON if enabled; application settings
cannot configure an external proxy. Interactive management-command output and test
runner progress are CLI output, not structured runtime log records.

## One SLO: open the dashboard entry point

**Demo journey:** open `/`; a signed-in user sees the personal dashboard, while an
anonymous user is directed to sign-in. Authentication and case scoping remain
covered by functional/security tests.

**Objective:** over a rolling **30-day** window, **99.9% of completed GET `/`
requests** return HTTP **200 or the expected 302 sign-in redirect** in **at most
1.0 second** of server time. A slow response or any other status is a bad event;
a response that is both slow and erroneous is counted only once. All traffic in
the metric counts, including the demo and probes. This SLO measures the entry
route, not a full login/upload/download transaction or the content's correctness.

PromQL for the measured good-event fraction (sum across service replicas):

```promql
sum(increase(lexflow_dashboard_request_duration_seconds_bucket{le="1.0",status=~"200|302"}[30d]))
/
sum(increase(lexflow_dashboard_requests_total[30d]))
```

A zero denominator means **no data**, not 100% success. Configure regular scrapes
and retain at least 30 days of data. App-local metrics cannot record requests
that never reach a worker or a total process outage; use an external HTTP probe
for that availability signal. Do not use this SLI alone to claim end-to-end uptime.

**Computed error budget:** `1 - 0.999 = 0.001`, or **0.1% of eligible requests**.
For `N` requests, budget is `0.001 × N` bad events; the largest permitted whole
number is `floor(0.001 × N)`.

| Completed requests in 30 days | Allowed bad events |
| --- | ---: |
| 1,000 | 1 |
| 10,000 | 10 |
| 100,000 | 100 |

For example, at 100,000 requests, 40 bad events consume **40%** of the budget,
leaving **60**. More than 100 breaches the objective. A 30-day time equivalent
is `30 × 24 × 60 × 60 × 0.001 = 2,592 seconds`, or **43 minutes 12 seconds**, but
this is illustrative only: the actual SLO budget is request-based and traffic
is not assumed uniform. Pause discretionary releases when the budget is exhausted
and prioritize reliability repairs. No observed 30-day budget consumption is
claimed until monitoring data exists.

## Outgoing calls and explicit deadlines

The application currently has no HTTP API, cloud SDK, or outbound webhook client.
The production call inventory is PostgreSQL, SMTP, ClamAV, and `pg_dump`:

| Outgoing operation | Enforced limit | Failure behavior |
| --- | --- | --- |
| PostgreSQL connection | 5 seconds per connection attempt | Connection error; no successful operation is claimed. |
| PostgreSQL interactive queries | 10 seconds per statement | Server cancels the statement; transaction rolls back. |
| PostgreSQL lock waits | 3 seconds | Server cancels blocked statements; transaction rolls back. |
| SMTP connect/read/write operations | 10 seconds, shared base setting | Django mail backend raises on transport failure; no unlimited socket wait. |
| ClamAV scan subprocess | Existing 30-second process deadline | Scan failure rejects publication; staged files are cleaned up. |
| Backup `pg_dump` | 120-second process deadline, 5-second DB connect, 120-second statements, 3-second lock wait | Raises a generic `CommandError`; temporary backup staging is removed. |
| CI advisory-service requests (`pip-audit`) | Explicit 15-second request timeout | Audit failure stops CI. GitHub job also has a 15-minute limit. |

These are operation/statement limits, not a single deadline for an entire HTTP
request, DNS resolution, or operating-system filesystem I/O. They do not establish
hard bounds for every network-failure mode; unreachable connections fail on the
connection timeout, while server-side query cancellation requires a reachable
server. Local private-file storage makes no outgoing network call. Recovery and
settings-check test subprocesses also have finite deadlines. When adding a new
network integration, include explicit connection/read deadlines and timeout
failure coverage with the change.
