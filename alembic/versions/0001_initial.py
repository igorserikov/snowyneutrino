"""Initial SnowTrino schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("clusters",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(63), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False), sa.Column("region", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("endpoint", sa.String(512)),
        sa.Column("namespace", sa.String(63), nullable=False), sa.Column("trino_version", sa.String(32), nullable=False),
        sa.Column("worker_count", sa.Integer(), nullable=False), sa.Column("worker_cpu", sa.String(16), nullable=False),
        sa.Column("worker_memory", sa.String(16), nullable=False), sa.Column("coordinator_cpu", sa.String(16), nullable=False),
        sa.Column("coordinator_memory", sa.String(16), nullable=False), sa.Column("terraform_state_ref", sa.String(512)),
        sa.Column("last_error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_cluster_name"))
    op.create_table("operations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()), sa.Column("logs", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_index("ix_operations_cluster_id", "operations", ["cluster_id"])
    op.create_index("ix_operations_status", "operations", ["status"])
    op.create_table("query_history",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False), sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()), sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_query_history_cluster_id", "query_history", ["cluster_id"])

def downgrade():
    op.drop_table("query_history")
    op.drop_table("operations")
    op.drop_table("clusters")
