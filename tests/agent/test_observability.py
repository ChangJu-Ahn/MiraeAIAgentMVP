import agent.observability as obs


def test_reset_and_collect_trace_json(monkeypatch):
    from types import SimpleNamespace

    from opentelemetry import trace

    calls = []

    class FakeSpan:
        def to_json(self, indent):
            assert indent == 2
            return '{"name": "agent-run"}'

    class FakeExporter:
        def clear(self):
            calls.append("clear")

        def get_finished_spans(self):
            calls.append("get")
            return [FakeSpan()]

    monkeypatch.setattr(obs, "_span_exporter", FakeExporter(), raising=False)
    monkeypatch.setattr(
        trace,
        "get_tracer_provider",
        lambda: SimpleNamespace(force_flush=lambda: calls.append("flush")),
    )

    obs.reset_trace()
    raw = obs.collect_trace_json()

    assert calls == ["clear", "flush", "get"]
    assert raw == '[\n{"name": "agent-run"}\n]'


def test_setup_observability_configures_inmemory_without_connection(monkeypatch):
    from unittest.mock import patch

    from config.settings import Settings

    monkeypatch.setattr(obs, "_configured", False, raising=False)
    monkeypatch.setattr(obs, "_span_exporter", None, raising=False)
    monkeypatch.delenv("APPINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(obs, "get_settings", lambda: Settings(_env_file=None))
    with patch("agent_framework.observability.configure_otel_providers") as mock_cfg, patch(
        "agent_framework.observability.enable_instrumentation"
    ) as mock_enable:
        assert obs.setup_observability() is True
        exporters = mock_cfg.call_args.kwargs["exporters"]
        assert exporters == [obs._span_exporter]
        mock_enable.assert_called_once_with(enable_sensitive_data=True)
    assert obs._span_exporter is not None


def test_setup_observability_idempotent_guard(monkeypatch):
    monkeypatch.setattr(obs, "_configured", True, raising=False)
    assert obs.setup_observability() is True


def test_setup_observability_configures_when_connected(monkeypatch):
    from unittest.mock import patch

    from config.settings import Settings

    monkeypatch.setattr(obs, "_configured", False, raising=False)
    test_conn = (
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
        "IngestionEndpoint=https://x.in.applicationinsights.azure.com/"
    )
    monkeypatch.setattr(
        obs,
        "get_settings",
        lambda: Settings(_env_file=None, appinsights_connection_string=test_conn),
    )
    trace_exporter = object()
    log_exporter = object()
    metric_exporter = object()
    with patch(
        "azure.monitor.opentelemetry.exporter.AzureMonitorTraceExporter",
        return_value=trace_exporter,
    ) as mock_exporter, patch(
        "azure.monitor.opentelemetry.exporter.AzureMonitorLogExporter",
        return_value=log_exporter,
    ) as mock_log_exporter, patch(
        "azure.monitor.opentelemetry.exporter.AzureMonitorMetricExporter",
        return_value=metric_exporter,
    ) as mock_metric_exporter, patch(
        "agent_framework.observability.configure_otel_providers"
    ) as mock_cfg, patch(
        "agent_framework.observability.enable_instrumentation"
    ) as mock_enable:
        assert obs.setup_observability() is True
        mock_exporter.assert_called_once_with(connection_string=test_conn)
        mock_log_exporter.assert_called_once_with(connection_string=test_conn)
        mock_metric_exporter.assert_called_once_with(connection_string=test_conn)
        exporters = mock_cfg.call_args.kwargs["exporters"]
        assert exporters == [
            obs._span_exporter,
            trace_exporter,
            log_exporter,
            metric_exporter,
        ]
        assert mock_cfg.call_args.kwargs["enable_sensitive_data"] is True
        mock_enable.assert_called_once_with(enable_sensitive_data=True)
