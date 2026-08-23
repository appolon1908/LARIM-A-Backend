"""production primitives

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("response_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_subject","operation","idempotency_key",name="uq_idempotency_actor_op_key"),
    )
    op.create_table(
        "integration_status",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(80), nullable=False, unique=True),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("readiness", sa.String(32), nullable=False, server_default="UNCONFIGURED"),
        sa.Column("last_error", sa.Text()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    )

def downgrade():
    op.drop_table("integration_status")
    op.drop_table("idempotency_records")
