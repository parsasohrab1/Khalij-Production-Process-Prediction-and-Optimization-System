"""Shared Prometheus metrics for the microservices (phase 8 / NFR-PER-02)."""
from __future__ import annotations

import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROM_AVAILABLE = False

_REQUEST_COUNT: Counter | None = None
_REQUEST_LATENCY: Histogram | None = None
_IN_PROGRESS: Gauge | None = None
_SERVICE_INFO: Info | None = None
_COUNTERS: dict[str, Counter] = {}
_HISTOGRAMS: dict[str, Histogram] = {}
_initialized_for: str | None = None


def _ensure_metrics(service_name: str) -> None:
    global _REQUEST_COUNT, _REQUEST_LATENCY, _IN_PROGRESS, _SERVICE_INFO, _initialized_for
    if not _PROM_AVAILABLE:
        return
    if _initialized_for == service_name:
        return
    _initialized_for = service_name
    _REQUEST_COUNT = Counter(
        "khalij_http_requests_total",
        "Total HTTP requests",
        ["service", "method", "path", "status"],
    )
    _REQUEST_LATENCY = Histogram(
        "khalij_http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["service", "method", "path"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
    )
    _IN_PROGRESS = Gauge(
        "khalij_http_requests_in_progress",
        "In-progress HTTP requests",
        ["service"],
    )
    _SERVICE_INFO = Info("khalij_service", "Service metadata")
    _SERVICE_INFO.info({"name": service_name, "phase": "8"})


def inc_counter(name: str, *, service: str, labels: dict[str, str] | None = None, amount: float = 1.0) -> None:
    if not _PROM_AVAILABLE:
        return
    labels = labels or {}
    if name not in _COUNTERS:
        _COUNTERS[name] = Counter(name, f"Custom counter {name}", ["service", *sorted(labels.keys())])
    _COUNTERS[name].labels(service=service, **labels).inc(amount)


def observe_seconds(name: str, seconds: float, *, service: str, labels: dict[str, str] | None = None) -> None:
    if not _PROM_AVAILABLE:
        return
    labels = labels or {}
    if name not in _HISTOGRAMS:
        _HISTOGRAMS[name] = Histogram(
            name,
            f"Custom histogram {name}",
            ["service", *sorted(labels.keys())],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
        )
    _HISTOGRAMS[name].labels(service=service, **labels).observe(seconds)


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str):
        super().__init__(app)
        self.service_name = service_name
        _ensure_metrics(service_name)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not _PROM_AVAILABLE or _REQUEST_COUNT is None:
            return await call_next(request)
        path = request.url.path
        if path in {"/metrics", "/health", "/health/live", "/health/ready"}:
            return await call_next(request)
        route = request.scope.get("route")
        path_template = getattr(route, "path", path) if route else path
        method = request.method
        if _IN_PROGRESS:
            _IN_PROGRESS.labels(service=self.service_name).inc()
        t0 = time.perf_counter()
        status = "500"
        try:
            response = await call_next(request)
            status = str(response.status_code)
            return response
        finally:
            elapsed = time.perf_counter() - t0
            if _IN_PROGRESS:
                _IN_PROGRESS.labels(service=self.service_name).dec()
            if _REQUEST_COUNT:
                _REQUEST_COUNT.labels(
                    service=self.service_name, method=method, path=path_template, status=status
                ).inc()
            if _REQUEST_LATENCY:
                _REQUEST_LATENCY.labels(
                    service=self.service_name, method=method, path=path_template
                ).observe(elapsed)


def install_prometheus_metrics(app: FastAPI, *, service_name: str) -> None:
    _ensure_metrics(service_name)
    app.add_middleware(PrometheusMiddleware, service_name=service_name)

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        if not _PROM_AVAILABLE:
            return Response("# prometheus_client not installed\n", media_type="text/plain")
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def prometheus_available() -> bool:
    return _PROM_AVAILABLE
