# SnowTrino

SnowTrino is a FastAPI and server-rendered starter control plane for Trino clusters. It currently provides a database-backed cluster/operation API, a small web UI, SQL history, and a **mock infrastructure provider** for local lifecycle demos.

## Run with Docker Compose

Requirements: Docker Desktop with Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open http://localhost:8000. PostgreSQL stores clusters, operations, and query history. The dedicated worker polls the operations table; lifecycle requests return HTTP 202 and survive web-process restarts. The default `INFRASTRUCTURE_MODE=mock` never calls AWS, Terraform, Helm, or Kubernetes. It exercises lifecycle state transitions with a demo endpoint. That endpoint is not a real Trino server, so SQL execution requires a separately configured, reachable Trino endpoint.

## Run locally without Docker

This setup uses SQLite. Copy the local example to `.env` so the API, migration command, and worker all read the same database URL:

```powershell
pip install -e '.[dev]'
Copy-Item .env.local.example .env
alembic upgrade head
```

Then, from the project root with the virtual environment active, start the API and worker in separate PowerShell windows:

```powershell
uvicorn snowtrino.main:app --reload
```

```powershell
python -m snowtrino.worker
```

The worker and API both load `.env` from the project root. Keep the same `.env` in use for both. `.env.example` is configured for Docker Compose, where the PostgreSQL host `db` is resolvable; it will not work when running commands directly from Windows. To switch modes, copy the matching example over `.env`.

## API

The `/api/v1` endpoints cover cluster create/list/details/start/stop/scale/delete, readiness, SQL execution/history, and operation status/logs. Infrastructure changes are queued in PostgreSQL. Incompatible lifecycle changes return HTTP 409. SQL is sent only through `trino-python-client`; result rows are capped by `TRINO_MAX_RESULT_ROWS`.

## Current implementation boundary

- The mock provider is the only working lifecycle backend.
- `TerraformAdapter` is a safe argument-list subprocess wrapper with timeout and bounded error output, but no provider module or cluster workspace is supplied yet.
- Helm deployment, real Trino readiness checks, and AWS EKS/VPC provisioning still need implementation before setting infrastructure mode to a real provider. Non-mock mode deliberately fails with an actionable configuration error rather than reporting fake success.
- Azure and GCP return unsupported-provider errors outside mock mode.
- Authentication is not implemented. Keep this service on a trusted local network until an authentication and authorization layer is added.

## AWS and network setup for a real deployment

The current repository does not provision AWS resources. When adding the AWS provider, use the standard AWS credential chain or an attached IAM role; never store access keys in this app or Terraform variables. Define least-privilege permissions scoped to the selected VPC, EKS cluster, node groups, IAM roles, load balancers, and required AWS Glue/S3 resources. Restrict Trino ingress to trusted application/operator networks, use TLS and authenticated Trino, and keep Terraform state and operation logs private. Choose a remote state backend with locking before multiple operators/workers use real infrastructure. `terraform destroy` must be reviewed against the cluster's state before operating on a real account.

## Tests and quality

Run `pytest`, `ruff check snowtrino tests`, and `mypy snowtrino` after installing the `dev` extra. Unit tests use SQLite and mocks and do not need cloud credentials. `alembic upgrade head` applies the initial PostgreSQL-compatible schema.

## Next implementation stage

Complete isolated per-cluster Terraform workspaces and a reviewed AWS EKS module, add a Helm release adapter for Trino plus Iceberg/Glue/S3 catalog settings, implement actual `/v1/info` readiness checks, then validate against a disposable AWS test account and Trino integration environment. Add authentication before exposing this app beyond a trusted local environment.
