import agent.observability as obs


def test_setup_observability_noop_without_connection(monkeypatch):
    monkeypatch.setattr(obs, "_configured", False, raising=False)
    monkeypatch.delenv("APPINSIGHTS_CONNECTION_STRING", raising=False)
    from config.settings import Settings

    monkeypatch.setattr(obs, "get_settings", lambda: Settings(_env_file=None))
    assert obs.setup_observability() is False


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
