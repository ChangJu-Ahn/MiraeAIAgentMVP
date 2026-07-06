from __future__ import annotations

from config.settings import get_settings

_configured = False


def setup_observability() -> bool:
    """Wire Azure Application Insights (OpenTelemetry) once per process.

    Records agent runs and tool calls (inputs=grounds, outputs=answers) as
    gen_ai spans when APPINSIGHTS_CONNECTION_STRING is set. No-op otherwise.
    """
    global _configured
    if _configured:
        return True
    conn = get_settings().appinsights_connection_string
    if not conn:
        return False

    from agent_framework.observability import configure_otel_providers, enable_instrumentation
    from azure.monitor.opentelemetry.exporter import (
        AzureMonitorLogExporter,
        AzureMonitorMetricExporter,
        AzureMonitorTraceExporter,
    )

    configure_otel_providers(
        exporters=[
            AzureMonitorTraceExporter(connection_string=conn),
            AzureMonitorLogExporter(connection_string=conn),
            AzureMonitorMetricExporter(connection_string=conn),
        ],
        enable_sensitive_data=True,
    )
    enable_instrumentation(enable_sensitive_data=True)
    _configured = True
    return True
