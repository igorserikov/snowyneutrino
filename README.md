# SnowTrino

SnowTrino is a FastAPI and server-rendered starter control plane for Trino clusters. It currently provides a database-backed cluster/operation API, a small web UI, SQL history, and a **mock infrastructure provider** for local lifecycle demos.

## Run with Docker Compose

Requirements: Docker Desktop with Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open http://localhost:8000. PostgreSQL stores clusters, operations, and query history. The dedicated worker polls the operations table; lifecycle requests return HTTP 202 and survive web-process restarts. In mock mode, the app uses one local Trino container and waits for `SELECT 1` to succeed before marking the cluster ready. The Trino HTTP port is bound to localhost only. Mock lifecycle actions update the app's cluster state; the shared Trino container itself stays running until Docker Compose stops it.

The local Trino image includes a read-only TPC-H sample catalog. For example, open the cluster's SQL page and run:

```sql
SELECT nationkey, name FROM tpch.tiny.nation LIMIT 10;
```

## Run locally without Docker

This setup uses SQLite and runs Trino in Docker. Copy the local example to `.env`, then start the Trino container:

```powershell
pip install -e '.[dev]'
Copy-Item .env.local.example .env
docker compose up -d trino
alembic upgrade head
```

Then, from the project root with the virtual environment active, start the API and worker in separate PowerShell windows:

```powershell
uvicorn snowtrino.main:app --reload
```

```powershell
python -m snowtrino.worker
```

The worker and API both load `.env` from the project root. Keep the same `.env` in use for both. `.env.example` is configured for the full Docker Compose stack, where the PostgreSQL and Trino service names are resolvable; it will not work when running Python commands directly from Windows. To switch modes, copy the matching example over `.env`.

## API

The `/api/v1` endpoints cover cluster create/list/details/start/stop/scale/delete, readiness, SQL execution/history, and operation status/logs. Infrastructure changes are queued in PostgreSQL. Incompatible lifecycle changes return HTTP 409. SQL is sent only through `trino-python-client`; result rows are capped by `TRINO_MAX_RESULT_ROWS`.

## Current implementation boundary

- The mock provider connects to one Dockerized local Trino instance. Create another mock cluster only after deleting the existing one. Stop and delete change SnowTrino's logical state; stop the Trino container separately with `docker compose stop trino` if you want to stop its process.
- `TerraformAdapter` is a safe argument-list subprocess wrapper with timeout and bounded error output, but no provider module or cluster workspace is supplied yet.
- Helm deployment, real Trino readiness checks, and AWS EKS/VPC provisioning still need implementation before setting infrastructure mode to a real provider. Non-mock mode deliberately fails with an actionable configuration error rather than reporting fake success.
- Azure and GCP return unsupported-provider errors outside mock mode.
- Authentication is not implemented. Keep this service on a trusted local network until an authentication and authorization layer is added.

## AWS and network setup for a real deployment

The current repository does not provision AWS resources. When adding the AWS provider, use the standard AWS credential chain or an attached IAM role; never store access keys in this app or Terraform variables. Define least-privilege permissions scoped to the selected VPC, EKS cluster, node groups, IAM roles, load balancers, and required AWS Glue/S3 resources. Restrict Trino ingress to trusted application/operator networks, use TLS and authenticated Trino, and keep Terraform state and operation logs private. Choose a remote state backend with locking before multiple operators/workers use real infrastructure. `terraform destroy` must be reviewed against the cluster's state before operating on a real account.

## Tests and quality

Run `pytest`, `ruff check snowtrino tests`, and `mypy snowtrino` after installing the `dev` extra. Unit tests use SQLite and mocks and do not need cloud credentials. `alembic upgrade head` applies the PostgreSQL- and SQLite-compatible schema.

## Next implementation stage

Complete isolated per-cluster Terraform workspaces and a reviewed AWS EKS module, add a Helm release adapter for Trino plus Iceberg/Glue/S3 catalog settings, implement actual `/v1/info` readiness checks, then validate against a disposable AWS test account and Trino integration environment. Add authentication before exposing this app beyond a trusted local environment.
