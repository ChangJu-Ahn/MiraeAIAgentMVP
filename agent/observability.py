from __future__ import annotations

from config.settings import get_settings

_configured = False


def setup_observability() -> bool:
    """Application Insights가 설정된 경우 Agent Framework trace를 내보낸다."""
    global _configured
    if _configured:
        return True

    connection_string = get_settings().appinsights_connection_string
    if not connection_string:
        return False

    from agent_framework.observability import configure_otel_providers, enable_instrumentation
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    exporter = AzureMonitorTraceExporter(connection_string=connection_string)
    configure_otel_providers(exporters=[exporter], enable_sensitive_data=True)
    enable_instrumentation(enable_sensitive_data=True)
    _configured = True
    return True
