# SnowTrino

SnowTrino is a FastAPI and server-rendered starter control plane for Trino clusters. It provides a database-backed cluster/operation API, a small web UI, SQL history, a mock provider for Compose demos, and a Terraform-backed local Docker provider.

## Run with Docker Compose

Requirements: Docker Desktop with Docker Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build --remove-orphans
```

Open http://localhost:8000. PostgreSQL stores clusters, operations, query history, and Iceberg catalog metadata. The API starts its operation worker automatically; queued lifecycle requests remain in the database across web-process restarts. In mock mode, the app uses one local Trino container and waits for `SELECT 1` to succeed before marking the cluster ready. The Trino HTTP and RustFS ports are bound to localhost only. Mock lifecycle actions update the app's cluster state; the shared Trino and RustFS services stay running until Docker Compose stops them.

The mock Trino image includes the read-only TPC-H sample catalog and a writable Iceberg catalog backed by RustFS, an S3-compatible object store. For example, open the cluster's SQL page and run:

```sql
SELECT nationkey, name FROM tpch.tiny.nation LIMIT 10;
```

Create and query an Iceberg table in the object store by running these statements one at a time:

```sql
CREATE SCHEMA iceberg.demo WITH (location = 's3://warehouse/demo/');
CREATE TABLE iceberg.demo.events (id bigint, message varchar) WITH (format = 'PARQUET');
INSERT INTO iceberg.demo.events VALUES (1, 'stored in RustFS');
SELECT * FROM iceberg.demo.events;
```

Run each statement separately. If upgrading an existing mock setup from JDBC catalog schema `V0`, the catalog configuration now uses `V1` and Trino migrates the metadata database on startup. Recreate Trino with:

```powershell
docker compose -f docker-compose.mock.yml up -d --force-recreate trino
```

After it starts, retry only the statement that failed; the schema and table may already have been created.

The RustFS console is available at http://localhost:9001 with the local demo credentials `minioadmin` / `minioadmin`.

The mock Trino also exposes the Compose PostgreSQL database as the `postgres` catalog. For example, list schemas and inspect the Iceberg JDBC catalog metadata:

```sql
SHOW SCHEMAS FROM postgres;
SHOW TABLES FROM postgres.public;
SELECT * FROM postgres.public.iceberg_tables;
```

The `hive` catalog uses an Apache Hive Metastore and stores Hive table data in RustFS. The mock catalog enables writes to non-managed (external) Hive tables, which lets the example `INSERT` work with Hive 4's metastore. Create and query a Hive table with:

```sql
CREATE SCHEMA hive.demo WITH (location = 's3://warehouse/hive/demo/');
CREATE TABLE hive.demo.events (id bigint, message varchar) WITH (format = 'PARQUET');
INSERT INTO hive.demo.events VALUES (1, 'stored in RustFS');
SELECT * FROM hive.demo.events;
```

Run these statements one at a time. The metastore database is persisted in the `hive_metastore_data` Compose volume.

### Snowflake-style stage commands

The SQL console also accepts a small Snowflake-inspired SQL layer for external stages. Stage definitions and `COPY INTO` load records are stored in the SnowTrino application database and scoped to a cluster. `CREATE STAGE` currently accepts an S3 or S3-compatible URL; access uses the application's `STAGE_S3_*` settings. The mock setup points these settings at RustFS.

Create a stage and list files in it (optionally with a path or regular expression):

```sql
CREATE STAGE incoming URL = 's3://warehouse/incoming/';
SHOW STAGES;
SHOW STAGES LIKE 'in%';
LIST @incoming;
LIST @incoming/daily PATTERN = '.*[.]csv';
```

Load matching CSV files into an existing Hive table:

```sql
COPY INTO hive.demo.events
FROM @incoming
PATTERN = '.*[.]csv'
FILE_FORMAT = (TYPE = CSV);
```

`COPY INTO` supports `FILES`, `PATTERN`, and the CSV, JSON, Parquet, and ORC formats. Without a `FILE_FORMAT` clause it assumes CSV; CSV headers are treated as data because header options are not implemented. File columns must match the target table by position and type. Successfully loaded files are skipped on later runs unless their S3 ETag or modification time changes. SnowTrino registers each selected file through a temporary external Hive table, then Trino reads it and inserts into the target table. Stage SQL is a limited subset: internal stages, file format objects, cloud-specific credentials in SQL, and other Snowflake copy options are not implemented.

For the host-run API used with `docker-compose.mock.yml`, set `STAGE_S3_ENDPOINT=http://localhost:9000` and the RustFS demo credentials in `.env`. For the full Compose stack, the web service is configured to reach RustFS at `http://rustfs:9000`.

## Run locally with mock Trino

To run the mock Trino, RustFS, and their Iceberg catalog database in Docker while running the SnowTrino API from the host, use the standalone Compose file. Trino is published at `http://localhost:8080`, RustFS's S3 API at `http://localhost:9000`, and the RustFS console at `http://localhost:9001`:

```powershell
Copy-Item .env.mock.example .env
docker compose -f docker-compose.mock.yml up -d
alembic upgrade head
```

Then start the API; it starts the worker automatically:

```powershell
uvicorn snowtrino.main:app --reload
```

Stop the mock Trino service with `docker compose -f docker-compose.mock.yml down`.

## Run locally with Terraform-managed Trino

Requirements: Docker Desktop and Terraform 1.5 or newer installed and available in `PATH`. This setup runs the API and its embedded worker on the host, uses SQLite, and lets Terraform create the Trino container. Copy the local example to `.env`:

```powershell
pip install -e '.[dev]'
Copy-Item .env.local.example .env
docker compose stop trino
alembic upgrade head
```

Then, from the project root with the virtual environment active, start the API; it starts the worker automatically:

```powershell
uvicorn snowtrino.main:app --reload
```


The API and embedded worker load `.env` from the project root. If you started Trino through the previous Compose mock setup, stop that service first to free port 8080. Delete any existing cluster in the dashboard before creating the single Terraform-managed cluster. When a cluster is created, the worker runs Terraform `init`, `plan`, and `apply`; the local Docker provider creates `snowtrino-local-trino` and publishes its HTTP port on `127.0.0.1:8080`. Stop destroys that container, Start recreates it, and Delete destroys it and removes the cluster record. Terraform state is local under `terraform/local` and is ignored by Git. Scaling a single local Trino container is not supported. `.env.example` is for the full Docker Compose stack, which keeps its standalone Trino service in mock mode.

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
