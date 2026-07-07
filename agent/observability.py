from __future__ import annotations

from config.settings import get_settings

_configured = False
_span_exporter = None  # InMemorySpanExporter, UI 디버그용 raw 트레이스 캡처


def setup_observability() -> bool:
    """OpenTelemetry(gen_ai 스팬) 계측을 프로세스당 한 번 설정한다.

    항상 인메모리 익스포터를 붙여 디버그 모드에서 raw 트레이스를 볼 수 있게 하고,
    APPINSIGHTS_CONNECTION_STRING이 있으면 Azure Application Insights로도 내보낸다.
    """
    global _configured, _span_exporter
    if _configured:
        return True

    from agent_framework.observability import configure_otel_providers, enable_instrumentation
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    _span_exporter = InMemorySpanExporter()
    exporters: list = [_span_exporter]

    conn = get_settings().appinsights_connection_string
    if conn:
        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorLogExporter,
            AzureMonitorMetricExporter,
            AzureMonitorTraceExporter,
        )

        exporters += [
            AzureMonitorTraceExporter(connection_string=conn),
            AzureMonitorLogExporter(connection_string=conn),
            AzureMonitorMetricExporter(connection_string=conn),
        ]

    configure_otel_providers(exporters=exporters, enable_sensitive_data=True)
    enable_instrumentation(enable_sensitive_data=True)
    _configured = True
    return True


def reset_trace() -> None:
    """다음 실행의 스팬만 모으기 위해 캡처 버퍼를 비운다 (턴 시작 시 호출)."""
    if _span_exporter is not None:
        _span_exporter.clear()


def collect_trace_json() -> str:
    """이번 실행에서 수집된 스팬을 OpenTelemetry 표준 JSON 배열 문자열로 반환.

    스팬이 없으면 빈 문자열. 배치 익스포터를 대비해 먼저 force_flush 한다.
    """
    if _span_exporter is None:
        return ""
    from opentelemetry import trace as _trace

    flush = getattr(_trace.get_tracer_provider(), "force_flush", None)
    if callable(flush):
        flush()
    spans = _span_exporter.get_finished_spans()
    if not spans:
        return ""
    return "[\n" + ",\n".join(s.to_json(indent=2) for s in spans) + "\n]"
