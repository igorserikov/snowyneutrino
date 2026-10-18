from pathlib import Path
from subprocess import CompletedProcess

import pytest

from snowtrino import infrastructure
from snowtrino.config import settings
from snowtrino.infrastructure import LocalTerraformProvider, TerraformAdapter, UnsupportedProviderError
from snowtrino.models import Cluster


def test_terraform_adapter_uses_argument_list_and_skips_variables_for_init(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return CompletedProcess(args, 0, "initialized", "")

    monkeypatch.setattr(settings, "terraform_binary", "terraform")
    monkeypatch.setattr(infrastructure.subprocess, "run", fake_run)

    output = TerraformAdapter(tmp_path).run("init", tmp_path, {"trino_version": "455"})

    assert output == "initialized"
    assert captured["args"] == ["terraform", "init", "-input=false"]
    assert "shell" not in captured["kwargs"]


def test_local_terraform_provider_applies_and_waits_for_trino(tmp_path, monkeypatch):
    class FakeAdapter:
        root = tmp_path

        def __init__(self):
            self.actions = []

        def run(self, action: str, workdir: Path, variables: dict[str, str]):
            self.actions.append((action, workdir, variables))
            return f"{action} complete"

    adapter = FakeAdapter()
    monkeypatch.setattr(infrastructure, "wait_for_trino", lambda endpoint, timeout: endpoint)
    provider = LocalTerraformProvider(adapter)  # type: ignore[arg-type]

    endpoint = provider.apply(Cluster(name="local-test", trino_version="455"))

    assert endpoint == infrastructure.LOCAL_TRINO_ENDPOINT
    assert [action for action, _, _ in adapter.actions] == ["init", "plan", "apply"]
    assert all(workdir == tmp_path / "local" for _, workdir, _ in adapter.actions)
    assert provider.logs


def test_local_terraform_stop_destroys_container_and_scale_is_rejected(tmp_path):
    class FakeAdapter:
        root = tmp_path

        def __init__(self):
            self.actions = []

        def run(self, action: str, workdir: Path, variables: dict[str, str]):
            self.actions.append(action)
            return "ok"

    adapter = FakeAdapter()
    provider = LocalTerraformProvider(adapter)  # type: ignore[arg-type]
    provider.workdir.mkdir()
    (provider.workdir / "terraform.tfstate").write_text("{}", encoding="utf-8")

    provider.stop(Cluster(name="local-test", trino_version="455"))

    assert adapter.actions == ["init", "destroy"]
    with pytest.raises(UnsupportedProviderError, match="Scaling a single local"):
        provider.scale(Cluster(name="local-test", trino_version="455"), 3)
