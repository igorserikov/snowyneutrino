import json
import time

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from snowtrino.config import settings
from snowtrino.db import SessionLocal
from snowtrino.models import Cluster, ClusterStatus, Operation, QueryRecord
from snowtrino.query import encode_result, execute
from snowtrino.schemas import ClusterCreate, QueryRequest, ScaleRequest

app = FastAPI(title="SnowTrino", version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def operation(db: Session, cluster: Cluster, kind: str, payload: dict | None = None) -> Operation:
    op = Operation(cluster_id=cluster.id, kind=kind, payload=json.dumps(payload or {}))
    db.add(op)
    db.commit()
    db.refresh(op)
    return op


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/v1/clusters")
def list_clusters(db: Session = Depends(get_db)):
    return db.scalars(select(Cluster).where(Cluster.status != ClusterStatus.deleted).order_by(Cluster.created_at.desc())).all()


@app.post("/api/v1/clusters", status_code=status.HTTP_202_ACCEPTED)
def create_cluster(body: ClusterCreate, db: Session = Depends(get_db)):
    mock_slot = "local" if settings.infrastructure_mode in {"mock", "local"} else None
    if mock_slot and db.scalar(select(Cluster.id).where(Cluster.status != ClusterStatus.deleted)):
        raise HTTPException(409, "Only one local Trino cluster is supported; delete the existing cluster first")
    cluster = Cluster(**body.model_dump(), status=ClusterStatus.pending, mock_slot=mock_slot)
    db.add(cluster)
    try:
        db.flush()
        op = Operation(cluster_id=cluster.id, kind="create", payload="{}")
        db.add(op)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if mock_slot and db.scalar(select(Cluster.id).where(Cluster.status != ClusterStatus.deleted)):
            raise HTTPException(409, "Only one local Trino cluster is supported; delete the existing cluster first") from exc
        raise HTTPException(409, "A cluster with this name already exists") from exc
    return {"cluster_id": cluster.id, "operation_id": op.id, "status": op.status}


@app.get("/api/v1/clusters/{cluster_id}")
def get_cluster(cluster_id: str, db: Session = Depends(get_db)):
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.status == ClusterStatus.deleted:
        raise HTTPException(404, "Cluster not found")
    return cluster


def enqueue_state(cluster_id: str, kind: str, expected: set[str], new_status: str,
                  db: Session, payload: dict | None = None):
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.status == ClusterStatus.deleted:
        raise HTTPException(404, "Cluster not found")
    if cluster.status not in expected:
        raise HTTPException(409, f"Cannot {kind} cluster while it is {cluster.status}")
    cluster.status = new_status
    cluster.last_error = None
    op = Operation(cluster_id=cluster.id, kind=kind, payload=json.dumps(payload or {}))
    db.add(op)
    db.commit()
    return {"cluster_id": cluster.id, "operation_id": op.id, "status": op.status}


@app.post("/api/v1/clusters/{cluster_id}/start", status_code=202)
def start_cluster(cluster_id: str, db: Session = Depends(get_db)):
    return enqueue_state(cluster_id, "start", {"stopped", "failed"}, "starting", db)


@app.post("/api/v1/clusters/{cluster_id}/stop", status_code=202)
def stop_cluster(cluster_id: str, db: Session = Depends(get_db)):
    return enqueue_state(cluster_id, "stop", {"running"}, "stopping", db)


@app.post("/api/v1/clusters/{cluster_id}/scale", status_code=202)
def scale_cluster(cluster_id: str, body: ScaleRequest, db: Session = Depends(get_db)):
    return enqueue_state(cluster_id, "scale", {"running"}, "updating", db, body.model_dump())


@app.delete("/api/v1/clusters/{cluster_id}", status_code=202)
def delete_cluster(cluster_id: str, db: Session = Depends(get_db)):
    return enqueue_state(cluster_id, "delete", {"running", "stopped", "failed"}, "deleting", db)


@app.get("/api/v1/clusters/{cluster_id}/health")
def cluster_health(cluster_id: str, db: Session = Depends(get_db)):
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.status == ClusterStatus.deleted:
        raise HTTPException(404, "Cluster not found")
    return {"cluster_id": cluster.id, "status": cluster.status,
            "ready": cluster.status == "running" and bool(cluster.endpoint)}


@app.post("/api/v1/clusters/{cluster_id}/queries")
def run_query(cluster_id: str, body: QueryRequest, db: Session = Depends(get_db)):
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.status == ClusterStatus.deleted:
        raise HTTPException(404, "Cluster not found")
    if cluster.status != "running" or not cluster.endpoint:
        raise HTTPException(409, "Cluster is not ready to accept queries")
    started = time.monotonic()
    try:
        columns, rows = execute(cluster.endpoint, body.sql)
        record = QueryRecord(cluster_id=cluster.id, sql=body.sql, status="succeeded",
                             duration_ms=int((time.monotonic()-started)*1000), row_count=len(rows),
                             result_json=encode_result(columns, rows))
        db.add(record)
        db.commit()
        return {"query_id": record.id, "status": record.status, "duration_ms": record.duration_ms,
                "row_count": record.row_count, "columns": columns, "rows": rows}
    except Exception as exc:
        record = QueryRecord(cluster_id=cluster.id, sql=body.sql, status="failed",
                             duration_ms=int((time.monotonic()-started)*1000), error=str(exc)[:2000])
        db.add(record)
        db.commit()
        raise HTTPException(502, f"Trino query failed: {str(exc)[:1000]}") from exc


@app.get("/api/v1/clusters/{cluster_id}/queries")
def query_history(cluster_id: str, db: Session = Depends(get_db)):
    if not db.get(Cluster, cluster_id):
        raise HTTPException(404, "Cluster not found")
    return db.scalars(select(QueryRecord).where(QueryRecord.cluster_id == cluster_id)
                      .order_by(QueryRecord.created_at.desc()).limit(100)).all()


@app.get("/api/v1/operations/{operation_id}")
def get_operation(operation_id: str, db: Session = Depends(get_db)):
    op = db.get(Operation, operation_id)
    if not op:
        raise HTTPException(404, "Operation not found")
    return op


@app.get("/api/v1/operations/{operation_id}/logs")
def operation_logs(operation_id: str, db: Session = Depends(get_db)):
    op = db.get(Operation, operation_id)
    if not op:
        raise HTTPException(404, "Operation not found")
    return {"operation_id": op.id, "logs": op.logs, "error": op.error}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    clusters = db.scalars(select(Cluster).where(Cluster.status != ClusterStatus.deleted)
                          .order_by(Cluster.created_at.desc())).all()
    operations = db.scalars(select(Operation).order_by(Operation.created_at.desc()).limit(10)).all()
    counts = {"total": len(clusters), "running": sum(c.status == "running" for c in clusters),
              "stopped": sum(c.status == "stopped" for c in clusters),
              "failed": sum(c.status == "failed" for c in clusters)}
    return templates.TemplateResponse(request, "dashboard.html", {"clusters": clusters,
                                        "operations": operations, "counts": counts,
                                        "infrastructure_mode": settings.infrastructure_mode})


@app.get("/fragments/clusters", response_class=HTMLResponse)
def cluster_rows(request: Request, db: Session = Depends(get_db)):
    clusters = db.scalars(select(Cluster).where(Cluster.status != ClusterStatus.deleted)
                          .order_by(Cluster.created_at.desc())).all()
    return templates.TemplateResponse(request, "cluster_rows.html", {"clusters": clusters})


@app.get("/clusters/{cluster_id}", response_class=HTMLResponse)
def cluster_page(request: Request, cluster_id: str, db: Session = Depends(get_db)):
    cluster = db.get(Cluster, cluster_id)
    if not cluster or cluster.status == "deleted":
        raise HTTPException(404, "Cluster not found")
    queries = db.scalars(select(QueryRecord).where(QueryRecord.cluster_id == cluster_id)
                         .order_by(QueryRecord.created_at.desc()).limit(20)).all()
    return templates.TemplateResponse(request, "cluster.html", {"cluster": cluster, "queries": queries})
