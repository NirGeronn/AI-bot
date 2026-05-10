"""Observability scaffolding — OpenTelemetry traces + Prometheus /metrics.

All initialization is opt-in via env vars. Without them, this module is a no-op
and adds zero overhead. Designed to never raise at import or init time.

Env vars:
  OTEL_EXPORTER_OTLP_ENDPOINT  — enable OTLP traces (e.g. http://localhost:4318)
  OTEL_SERVICE_NAME            — service name (default 'ai-bot')
  PROMETHEUS_PORT              — enable Prometheus HTTP server on this port (e.g. 9100)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_state = {"otel_initialized": False, "prom_initialized": False, "tracer": None}


def init_otel() -> None:
    if _state["otel_initialized"]:
        return
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug("OTEL disabled (no OTEL_EXPORTER_OTLP_ENDPOINT)")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "ai-bot")})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")))
        trace.set_tracer_provider(provider)
        _state["tracer"] = trace.get_tracer("ai-bot")
        _state["otel_initialized"] = True
        logger.info(f"OTEL traces enabled → {endpoint}")
    except ImportError as e:
        logger.warning(f"OTEL packages not installed; skipping ({e})")
    except Exception as e:
        logger.error(f"OTEL init failed: {e}")


def init_prometheus() -> None:
    if _state["prom_initialized"]:
        return
    port_str = os.environ.get("PROMETHEUS_PORT")
    if not port_str:
        logger.debug("Prometheus disabled (no PROMETHEUS_PORT)")
        return
    try:
        port = int(port_str)
        from prometheus_client import start_http_server, Counter, Histogram
        # Define some default metrics so the endpoint isn't empty
        global TOOL_CALLS, TOOL_LATENCY, AGENT_TURNS
        TOOL_CALLS = Counter("ai_bot_tool_calls_total", "Tool invocations", ["tool"])
        TOOL_LATENCY = Histogram("ai_bot_tool_latency_seconds", "Tool latency", ["tool"])
        AGENT_TURNS = Counter("ai_bot_agent_turns_total", "Agent turns", ["status"])
        start_http_server(port)
        _state["prom_initialized"] = True
        logger.info(f"Prometheus metrics enabled on :{port}")
    except ImportError as e:
        logger.warning(f"prometheus_client not installed; skipping ({e})")
    except Exception as e:
        logger.error(f"Prometheus init failed: {e}")


def init_observability() -> None:
    init_otel()
    init_prometheus()


def get_tracer():
    return _state.get("tracer")


# Convenience metric refs that no-op if Prometheus wasn't initialized.
class _NoopMetric:
    def labels(self, *a, **k): return self
    def inc(self, *a, **k): pass
    def observe(self, *a, **k): pass
    def time(self):
        from contextlib import nullcontext
        return nullcontext()


TOOL_CALLS = _NoopMetric()
TOOL_LATENCY = _NoopMetric()
AGENT_TURNS = _NoopMetric()
