"""Persist explainable dispatch scores and travel-estimate provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "dispatch_offers",
        sa.Column(
            "ranking_details", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
    )
    op.create_index(
        "ix_offer_provider_history", "dispatch_offers", ["provider_id", "created_at", "status"]
    )


def downgrade():
    raise RuntimeError("Preserve offer-ranking history during reviewed rollback")
