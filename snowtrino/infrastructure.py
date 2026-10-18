import json
import subprocess
import tempfile
import time
from pathlib import Path

from snowtrino.config import settings
from snowtrino.models import Cluster
from snowtrino.query import check_ready


class UnsupportedProviderError(RuntimeError):
    pass


class MockProvider:
    """Uses the single local Trino service configured for mock mode."""

    def _endpoint_when_ready(self) -> str:
        endpoint = settings.mock_trino_endpoint.rstrip("/")
        deadline = time.monotonic() + settings.mock_trino_startup_timeout_seconds
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

    def apply(self, cluster: Cluster) -> str:
        return self._endpoint_when_ready()

    def start(self, cluster: Cluster) -> str:
        return self._endpoint_when_ready()

    def stop(self, cluster: Cluster) -> None:
        return None

    def scale(self, cluster: Cluster, worker_count: int) -> None:
        return None

    def destroy(self, cluster: Cluster) -> None:
        return None


class TerraformAdapter:
    """Safe subprocess wrapper. Requires an operator supplied, reviewed module."""

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
        for key, value in (variables or {}).items():
            if not key.replace("_", "").isalnum():
                raise ValueError("Invalid Terraform variable name")
            args.extend([f"-var={key}={value}"])
        result = subprocess.run(args, cwd=workdir, capture_output=True, text=True,
                                timeout=settings.terraform_timeout_seconds, check=False)
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
    if provider != "AWS":
        raise UnsupportedProviderError(f"{provider} infrastructure is not implemented; use mock mode")
    raise RuntimeError("AWS deployment module is not configured. Set INFRASTRUCTURE_MODE=mock for demos.")
