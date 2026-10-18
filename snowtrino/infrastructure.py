import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from snowtrino.config import settings
from snowtrino.models import Cluster
from snowtrino.query import check_ready


class UnsupportedProviderError(RuntimeError):
    pass


LOCAL_TRINO_ENDPOINT = "http://127.0.0.1:8080"


def wait_for_trino(endpoint: str, timeout_seconds: int) -> str:
    endpoint = endpoint.rstrip("/")
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if check_ready(endpoint):
                return endpoint
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    detail = f" Last connection error: {last_error}" if last_error else ""
    raise RuntimeError(f"Local Trino did not become ready before timeout.{detail}")


class MockProvider:
    """Uses the single local Trino service configured for mock mode."""

    def apply(self, cluster: Cluster) -> str:
        return wait_for_trino(settings.mock_trino_endpoint,
                              settings.mock_trino_startup_timeout_seconds)

    def start(self, cluster: Cluster) -> str:
        return wait_for_trino(settings.mock_trino_endpoint,
                              settings.mock_trino_startup_timeout_seconds)

    def stop(self, cluster: Cluster) -> None:
        return None

    def scale(self, cluster: Cluster, worker_count: int) -> None:
        return None

    def destroy(self, cluster: Cluster) -> None:
        return None


class LocalTerraformProvider:
    """Manages one local Trino container through the Terraform Docker provider."""

    def __init__(self, adapter: "TerraformAdapter | None" = None) -> None:
        self.adapter = adapter or TerraformAdapter()
        self.workdir = self.adapter.root / "local"
        self.logs: list[str] = []
        self.catalog_path = str((Path(__file__).resolve().parents[1] / "trino" / "catalog").resolve())

    def _variables(self, cluster: Cluster) -> dict[str, str]:
        docker_host = ("npipe:////./pipe/docker_engine" if os.name == "nt"
                       else "unix:///var/run/docker.sock")
        return {"trino_version": cluster.trino_version, "catalog_path": self.catalog_path,
                "docker_host": docker_host}

    def _run(self, action: str, cluster: Cluster) -> None:
        try:
            output = self.adapter.run(action, self.workdir, self._variables(cluster))
        except Exception as exc:
            self.logs.append(f"terraform {action} failed:\n{str(exc)[-20000:]}\n")
            raise
        self.logs.append(f"terraform {action}:\n{output[-20000:]}\n")

    def _apply(self, cluster: Cluster) -> str:
        self._run("init", cluster)
        self._run("plan", cluster)
        self._run("apply", cluster)
        return wait_for_trino(LOCAL_TRINO_ENDPOINT,
                              settings.local_trino_startup_timeout_seconds)

    def apply(self, cluster: Cluster) -> str:
        return self._apply(cluster)

    def start(self, cluster: Cluster) -> str:
        return self._apply(cluster)

    def stop(self, cluster: Cluster) -> None:
        # Local stop removes the container; start recreates it from the same Terraform state.
        if not (self.workdir / "terraform.tfstate").exists():
            return
        self._run("init", cluster)
        self._run("destroy", cluster)

    def scale(self, cluster: Cluster, worker_count: int) -> None:
        raise UnsupportedProviderError("Scaling a single local Docker Trino container is not supported")

    def destroy(self, cluster: Cluster) -> None:
        if not (self.workdir / "terraform.tfstate").exists():
            return
        self._run("init", cluster)
        self._run("destroy", cluster)


class TerraformAdapter:
    """Safe subprocess wrapper for Terraform modules."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.terraform_root).resolve()

    def run(self, action: str, workdir: Path, variables: dict[str, str] | None = None) -> str:
        if action not in {"init", "plan", "apply", "destroy"}:
            raise ValueError("Unsupported Terraform action")
        if action != "init" and not (workdir / ".terraform").exists():
            raise RuntimeError("Terraform directory is not initialized")
        args = [settings.terraform_binary, action, "-input=false"]
        if action in {"apply", "destroy"}:
            args.append("-auto-approve")
        variable_items = (variables or {}).items() if action != "init" else ()
        for key, value in variable_items:
            if not key.replace("_", "").isalnum():
                raise ValueError("Invalid Terraform variable name")
            args.extend([f"-var={key}={value}"])
        try:
            result = subprocess.run(args, cwd=workdir, capture_output=True, text=True,
                                    timeout=settings.terraform_timeout_seconds, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Terraform executable '{settings.terraform_binary}' was not found; install Terraform "
                "or set TERRAFORM_BINARY to its executable path"
            ) from exc
        output = (result.stdout + result.stderr)[-20000:]
        if result.returncode:
            raise RuntimeError(f"Terraform {action} failed: {output}")
        return output


class HelmAdapter:
    """Install or update a Trino chart using a generated, per-invocation values file."""

    def __init__(self, binary: str = "helm", timeout_seconds: int = 900) -> None:
        self.binary = binary
        self.timeout_seconds = timeout_seconds

    def upgrade(self, *, release: str, chart: str, namespace: str, values: dict[str, object],
                kube_context: str | None = None) -> str:
        # Values are written as JSON, which Helm accepts as YAML, avoiding shell interpolation.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as f:
            json.dump(values, f)
            values_path = Path(f.name)
        args = [self.binary, "upgrade", "--install", release, chart, "--namespace", namespace,
                "--create-namespace", "--wait", "--values", str(values_path)]
        if kube_context:
            args.extend(["--kube-context", kube_context])
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=self.timeout_seconds,
                                    check=False)
            output = (result.stdout + result.stderr)[-20000:]
            if result.returncode:
                raise RuntimeError(f"Helm upgrade failed: {output}")
            return output
        finally:
            values_path.unlink(missing_ok=True)


def provider_for(provider: str):
    if settings.infrastructure_mode == "mock":
        return MockProvider()
    if settings.infrastructure_mode == "local":
        return LocalTerraformProvider()
    if provider != "AWS":
        raise UnsupportedProviderError(f"{provider} infrastructure is not implemented; use mock mode")
    raise RuntimeError(
        "AWS deployment module is not configured. Use INFRASTRUCTURE_MODE=local for a local Docker "
        "Trino container or mock for Compose demos."
    )
