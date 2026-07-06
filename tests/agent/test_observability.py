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
