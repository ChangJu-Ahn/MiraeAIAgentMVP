import agent.observability as obs


def test_setup_observability_is_noop_without_connection(monkeypatch):
    from unittest.mock import patch

    from config.settings import Settings

    monkeypatch.setattr(obs, "_configured", False, raising=False)
    monkeypatch.delenv("APPINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(obs, "get_settings", lambda: Settings(_env_file=None))
    with patch("agent_framework.observability.configure_otel_providers") as mock_cfg, patch(
        "agent_framework.observability.enable_instrumentation"
    ) as mock_enable:
        assert obs.setup_observability() is False
        mock_cfg.assert_not_called()
        mock_enable.assert_not_called()


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
    exporter = object()
    with patch(
        "azure.monitor.opentelemetry.exporter.AzureMonitorTraceExporter",
        return_value=exporter,
    ) as mock_exporter, patch(
        "agent_framework.observability.configure_otel_providers"
    ) as mock_cfg, patch(
        "agent_framework.observability.enable_instrumentation"
    ) as mock_enable:
        assert obs.setup_observability() is True
        mock_exporter.assert_called_once_with(connection_string=test_conn)
        mock_cfg.assert_called_once_with(
            exporters=[exporter], enable_sensitive_data=True
        )
        mock_enable.assert_called_once_with(enable_sensitive_data=True)
