"""Durable database-backed operation worker. Run as a separate process."""
import json
import time
from datetime import datetime, timezone

from sqlalchemy import select

from snowtrino.db import SessionLocal
from snowtrino.infrastructure import UnsupportedProviderError, provider_for
from snowtrino.models import Cluster, Operation


def claim_one():
    with SessionLocal() as db:
        op = db.scalar(select(Operation).where(Operation.status == "queued")
                       .order_by(Operation.created_at).with_for_update(skip_locked=True).limit(1))
        if not op:
            return None
        op.status = "running"
        op.started_at = datetime.now(timezone.utc)
        op.attempts += 1
        db.commit()
        return op.id


def process(operation_id: str):
    with SessionLocal() as db:
        op = db.get(Operation, operation_id)
        if op is None:
            return
        cluster = db.get(Cluster, op.cluster_id)
        if cluster is None:
            op.status = "failed"
            op.error = "Cluster not found for operation"
            op.finished_at = datetime.now(timezone.utc)
            db.commit()
            return
        provider = None
        try:
            provider = provider_for(cluster.provider)
            op.logs += f"[{datetime.now(timezone.utc).isoformat()}] {op.kind} started\n"
            payload = json.loads(op.payload or "{}")
            if op.kind == "create":
                cluster.status = "provisioning"
                op.logs += "Provisioning local Trino infrastructure.\n"
                db.commit()
                cluster.status = "starting"
                cluster.endpoint = provider.apply(cluster)
                # The mock endpoint represents a simulated healthy deployment.
                cluster.status = "running"
            elif op.kind == "start":
                cluster.endpoint = provider.start(cluster)
                cluster.status = "running"
            elif op.kind == "stop":
                provider.stop(cluster)
                cluster.status = "stopped"
            elif op.kind == "scale":
                count = int(payload["worker_count"])
                provider.scale(cluster, count)
                cluster.worker_count = count
                cluster.status = "running"
            elif op.kind == "delete":
                provider.destroy(cluster)
                cluster.status = "deleted"
                cluster.endpoint = None
                cluster.mock_slot = None
            op.status = "succeeded"
        except Exception as exc:
            if op.kind == "scale" and isinstance(exc, UnsupportedProviderError) and cluster.endpoint:
                cluster.status = "running"
            else:
                cluster.status = "failed"
            cluster.last_error = str(exc)[:2000]
            op.status = "failed"
            op.error = str(exc)[:2000]
        finally:
            provider_logs = getattr(provider, "logs", []) if provider is not None else []
            if provider_logs:
                op.logs = (op.logs + "".join(provider_logs))[-20000:]
            op.logs += "Operation completed.\n" if op.status == "succeeded" else "Operation failed; see error field.\n"
            op.finished_at = datetime.now(timezone.utc)
            db.commit()


def main():
    while True:
        operation_id = claim_one()
        if operation_id:
            process(operation_id)
        else:
            time.sleep(1)


if __name__ == "__main__":
    main()
