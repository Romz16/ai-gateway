import json
import logging
from datetime import UTC, datetime
from typing import Any

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Telemetry:
    def __init__(self, endpoint: str = "") -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "gateway_requests_total", "HTTP requests", ["route", "status"], registry=self.registry
        )
        self.duration = Histogram(
            "gateway_request_seconds", "End-to-end latency", ["route"], registry=self.registry
        )
        self.inflight = Gauge(
            "gateway_requests_in_flight", "Active HTTP requests", registry=self.registry
        )
        self.provider_calls = Counter(
            "gateway_provider_requests_total",
            "Provider attempts",
            ["provider", "outcome"],
            registry=self.registry,
        )
        self.provider_duration = Histogram(
            "gateway_provider_seconds",
            "Provider attempt latency",
            ["provider"],
            registry=self.registry,
        )
        self.tokens = Counter(
            "gateway_tokens_total",
            "Reported or reserved tokens",
            ["provider", "direction"],
            registry=self.registry,
        )
        self.cost = Counter(
            "gateway_estimated_cost_usd_total",
            "Accounted estimated cost",
            ["provider", "model", "task"],
            registry=self.registry,
        )
        self.retries = Counter(
            "gateway_retries_total", "Retries", ["provider"], registry=self.registry
        )
        self.fallbacks = Counter(
            "gateway_fallbacks_total", "Fallback executions", registry=self.registry
        )
        self.circuits = Counter(
            "gateway_circuit_open_total", "Circuit openings", ["provider"], registry=self.registry
        )
        self.cache = Counter(
            "gateway_cache_total", "Cache lookups", ["outcome"], registry=self.registry
        )
        self.events = Counter(
            "gateway_events_total", "Safe operational events", ["event"], registry=self.registry
        )
        self.traces = TracerProvider(resource=Resource.create({"service.name": "ai-gateway"}))
        if endpoint:
            self.traces.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        self.tracer = self.traces.get_tracer("ai-gateway")

    def event(self, event: str, **fields: Any) -> None:
        # Callers supply identifiers and fixed enums only, never exceptions or payloads.
        self.events.labels(event=event).inc()
        logging.getLogger("gateway").info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "INFO",
                    "event": event,
                    **fields,
                }
            )
        )


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in ("httpx", "httpcore", "sqlalchemy", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
