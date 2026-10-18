"""Reserve a single local Trino slot for mock mode."""
from alembic import op
import sqlalchemy as sa

revision = "0002_mock_cluster_slot"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clusters") as batch_op:
        batch_op.add_column(sa.Column("mock_slot", sa.String(16), nullable=True))
        batch_op.create_unique_constraint("uq_cluster_mock_slot", ["mock_slot"])


def downgrade():
    with op.batch_alter_table("clusters") as batch_op:
        batch_op.drop_constraint("uq_cluster_mock_slot", type_="unique")
        batch_op.drop_column("mock_slot")
