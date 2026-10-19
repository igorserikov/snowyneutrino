# SnowTrino

SnowTrino is a FastAPI and server-rendered starter control plane for Trino clusters. It provides a database-backed cluster/operation API, a small web UI, SQL history, a mock provider for Compose demos, and a Terraform-backed local Docker provider.

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

## Run locally with mock Trino

To run only the mock Trino service in Docker and the SnowTrino API/worker from the host, use the standalone Compose file. It publishes Trino at the fixed local address `http://localhost:8080` and mounts the sample catalog:

```powershell
Copy-Item .env.mock.example .env
docker compose -f docker-compose.mock.yml up -d
alembic upgrade head
```

Then start the API and worker in separate PowerShell windows:

```powershell
uvicorn snowtrino.main:app --reload
```

```powershell
python -m snowtrino.worker
```

Stop the mock Trino service with `docker compose -f docker-compose.mock.yml down`.

## Run locally with Terraform-managed Trino

Requirements: Docker Desktop and Terraform 1.5 or newer installed and available in `PATH`. This setup runs the API and worker on the host, uses SQLite, and lets Terraform create the Trino container. Copy the local example to `.env`:

```powershell
pip install -e '.[dev]'
Copy-Item .env.local.example .env
docker compose stop trino
alembic upgrade head
```

Then, from the project root with the virtual environment active, start the API and worker in separate PowerShell windows:

```powershell
uvicorn snowtrino.main:app --reload
```

```powershell
python -m snowtrino.worker
```

The worker and API both load `.env` from the project root. Keep the same `.env` in use for both. If you started Trino through the previous Compose mock setup, stop that service first to free port 8080. Delete any existing cluster in the dashboard before creating the single Terraform-managed cluster. When a cluster is created, the worker runs Terraform `init`, `plan`, and `apply`; the local Docker provider creates `snowtrino-local-trino` and publishes its HTTP port on `127.0.0.1:8080`. Stop destroys that container, Start recreates it, and Delete destroys it and removes the cluster record. Terraform state is local under `terraform/local` and is ignored by Git. Scaling a single local Trino container is not supported. `.env.example` is for the full Docker Compose stack, which keeps its standalone Trino service in mock mode.

## API

The `/api/v1` endpoints cover cluster create/list/details/start/stop/scale/delete, readiness, SQL execution/history, and operation status/logs. Infrastructure changes are queued in the configured database. Incompatible lifecycle changes return HTTP 409. SQL is sent only through `trino-python-client`; result rows are capped by `TRINO_MAX_RESULT_ROWS`.

## Current implementation boundary

- The mock provider connects to the Trino service in Docker Compose and only simulates lifecycle changes. The local provider uses Terraform and the Docker provider to create one standalone Trino container.
- `TerraformAdapter` uses argument-list subprocess calls with timeouts and bounded output. The local Docker module is implemented; AWS infrastructure and isolated cloud workspaces are not.
- AWS Helm deployment, AWS EKS/VPC provisioning, and cloud Trino readiness checks still need implementation before setting infrastructure mode to a real cloud provider. Unsupported providers fail with an actionable configuration error rather than reporting fake success.
- Azure and GCP return unsupported-provider errors outside mock mode.
- Authentication is not implemented. Keep this service on a trusted local network until an authentication and authorization layer is added.

## AWS and network setup for a real deployment

The current repository does not provision AWS resources. When adding the AWS provider, use the standard AWS credential chain or an attached IAM role; never store access keys in this app or Terraform variables. Define least-privilege permissions scoped to the selected VPC, EKS cluster, node groups, IAM roles, load balancers, and required AWS Glue/S3 resources. Restrict Trino ingress to trusted application/operator networks, use TLS and authenticated Trino, and keep Terraform state and operation logs private. Choose a remote state backend with locking before multiple operators/workers use real infrastructure. `terraform destroy` must be reviewed against the cluster's state before operating on a real account.

## Tests and quality

Run `pytest`, `ruff check snowtrino tests`, and `mypy snowtrino` after installing the `dev` extra. Unit tests use SQLite and mocks and do not need cloud credentials. `alembic upgrade head` applies the PostgreSQL- and SQLite-compatible schema.

## Next implementation stage

Complete isolated per-cluster Terraform workspaces and a reviewed AWS EKS module, add a Helm release adapter for Trino plus Iceberg/Glue/S3 catalog settings, implement actual `/v1/info` readiness checks, then validate against a disposable AWS test account and Trino integration environment. Add authentication before exposing this app beyond a trusted local environment.
