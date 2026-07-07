import agent.observability as obs


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
        # App Insights 연결이 없어도 디버그용 인메모리 트레이싱은 항상 설정된다.
        assert obs.setup_observability() is True
        exporters = mock_cfg.call_args.kwargs["exporters"]
        assert len(exporters) == 1  # 인메모리 익스포터만 (Azure 없음)
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
    with patch("agent_framework.observability.configure_otel_providers") as mock_cfg, patch(
        "agent_framework.observability.enable_instrumentation"
    ) as mock_enable:
        assert obs.setup_observability() is True
        mock_cfg.assert_called_once()
        assert mock_cfg.call_args.kwargs["enable_sensitive_data"] is True
        mock_enable.assert_called_once_with(enable_sensitive_data=True)
