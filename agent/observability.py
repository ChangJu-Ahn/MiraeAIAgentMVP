from __future__ import annotations

from config.settings import get_settings

_configured = False
_span_exporter = None


def setup_observability() -> bool:
    """Configure in-memory debug tracing and optional Application Insights export."""
    global _configured, _span_exporter
    if _configured:
        return True

    from agent_framework.observability import configure_otel_providers, enable_instrumentation
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    _span_exporter = InMemorySpanExporter()
    exporters: list = [_span_exporter]

    connection_string = get_settings().appinsights_connection_string
    if connection_string:
        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorLogExporter,
            AzureMonitorMetricExporter,
            AzureMonitorTraceExporter,
        )

        exporters.extend(
            [
                AzureMonitorTraceExporter(connection_string=connection_string),
                AzureMonitorLogExporter(connection_string=connection_string),
                AzureMonitorMetricExporter(connection_string=connection_string),
            ]
        )

    configure_otel_providers(exporters=exporters, enable_sensitive_data=True)
    enable_instrumentation(enable_sensitive_data=True)
    _configured = True
    return True


def reset_trace() -> None:
    if _span_exporter is not None:
        _span_exporter.clear()


def collect_trace_json() -> str:
    if _span_exporter is None:
        return ""

    from opentelemetry import trace

    flush = getattr(trace.get_tracer_provider(), "force_flush", None)
    if callable(flush):
        flush()
    spans = _span_exporter.get_finished_spans()
    if not spans:
        return ""
    return "[\n" + ",\n".join(span.to_json(indent=2) for span in spans) + "\n]"
