import pytest

from snowtrino import infrastructure
from snowtrino.config import settings
from snowtrino.infrastructure import MockProvider
from snowtrino.models import Cluster


def test_mock_provider_waits_for_the_local_trino(monkeypatch):
    cluster = Cluster(name="test-cluster")
    ready = iter([False, True])
    monkeypatch.setattr(settings, "mock_trino_endpoint", "http://trino:8080/")
    monkeypatch.setattr(settings, "mock_trino_startup_timeout_seconds", 5)
    monkeypatch.setattr(infrastructure, "check_ready", lambda endpoint: next(ready))
    monkeypatch.setattr(infrastructure.time, "sleep", lambda _: None)

    assert MockProvider().apply(cluster) == "http://trino:8080"


def test_mock_provider_fails_when_trino_does_not_become_ready(monkeypatch):
    cluster = Cluster(name="test-cluster")
    monkeypatch.setattr(settings, "mock_trino_startup_timeout_seconds", 0)
    with pytest.raises(RuntimeError, match="did not become ready"):
        MockProvider().apply(cluster)
