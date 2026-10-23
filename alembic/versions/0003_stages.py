"""Persist external stage definitions and loaded-file state."""
from alembic import op
import sqlalchemy as sa


revision = "0003_stages"
down_revision = "0002_mock_cluster_slot"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("clusters.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("cluster_id", "name", name="uq_stage_cluster_name"),
    )
    op.create_index("ix_stages_cluster_id", "stages", ["cluster_id"])
    op.create_table(
        "stage_loads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stage_id", sa.String(36), sa.ForeignKey("stages.id"), nullable=False),
        sa.Column("target_table", sa.String(512), nullable=False),
        sa.Column("object_key", sa.String(2048), nullable=False),
        sa.Column("etag", sa.String(256)),
        sa.Column("last_modified", sa.DateTime(timezone=True)),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stage_id", "target_table", "object_key", name="uq_stage_load_object"),
    )
    op.create_index("ix_stage_loads_stage_id", "stage_loads", ["stage_id"])


def downgrade():
    op.drop_table("stage_loads")
    op.drop_table("stages")
