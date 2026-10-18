from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from snowtrino.db import Base


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ClusterStatus(StrEnum):
    pending = "pending"
    provisioning = "provisioning"
    starting = "starting"
    running = "running"
    updating = "updating"
    stopping = "stopping"
    stopped = "stopped"
    deleting = "deleting"
    deleted = "deleted"
    failed = "failed"


class Cluster(Base):
    __tablename__ = "clusters"
    __table_args__ = (UniqueConstraint("name", name="uq_cluster_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(63), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), default="AWS")
    region: Mapped[str] = mapped_column(String(64), default="us-east-1")
    status: Mapped[str] = mapped_column(String(20), default=ClusterStatus.pending)
    endpoint: Mapped[str | None] = mapped_column(String(512))
    namespace: Mapped[str] = mapped_column(String(63), default="default")
    trino_version: Mapped[str] = mapped_column(String(32), default="455")
    worker_count: Mapped[int] = mapped_column(Integer, default=2)
    worker_cpu: Mapped[str] = mapped_column(String(16), default="2")
    worker_memory: Mapped[str] = mapped_column(String(16), default="4Gi")
    coordinator_cpu: Mapped[str] = mapped_column(String(16), default="2")
    coordinator_memory: Mapped[str] = mapped_column(String(16), default="4Gi")
    terraform_state_ref: Mapped[str | None] = mapped_column(String(512))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    operations: Mapped[list["Operation"]] = relationship(back_populates="cluster")


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cluster: Mapped[Cluster] = relationship(back_populates="operations")


class QueryRecord(Base):
    __tablename__ = "query_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), index=True)
    sql: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
