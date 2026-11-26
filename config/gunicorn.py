"""Use application JSON logging for both Django and Gunicorn diagnostics."""

from prometheus_client import multiprocess

from config.settings.base import LOGGING

logconfig_dict = LOGGING
# Application middleware emits correlated completion records without raw URLs.
accesslog = None


def child_exit(server, worker):
    import os

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(worker.pid)
