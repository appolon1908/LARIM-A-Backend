"""marketplace core

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table("customers",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),
        sa.Column("identity_issuer",sa.String(255),nullable=False),
        sa.Column("identity_subject",sa.String(255),nullable=False),
        sa.Column("market_code",sa.String(16),nullable=False),
        sa.Column("preferred_language",sa.String(10),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("version",sa.BigInteger(),nullable=False),
        sa.UniqueConstraint("identity_issuer","identity_subject",name="uq_customer_identity"))
    op.create_table("customer_addresses",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),
        sa.Column("customer_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("customers.id",ondelete="CASCADE"),nullable=False),
        sa.Column("label",sa.String(80),nullable=False),sa.Column("place_type",sa.String(32),nullable=False),
        sa.Column("address_line_1",sa.String(255),nullable=False),sa.Column("city",sa.String(120),nullable=False),
        sa.Column("country_code",sa.String(2),nullable=False),sa.Column("latitude",sa.Numeric(9,6),nullable=False),
        sa.Column("longitude",sa.Numeric(9,6),nullable=False),sa.Column("access_notes",sa.Text()),sa.Column("active",sa.Boolean(),nullable=False))
    op.create_table("device_registrations",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("identity_subject",sa.String(255),nullable=False),
        sa.Column("platform",sa.String(16),nullable=False),sa.Column("token",sa.String(512),nullable=False,unique=True),
        sa.Column("active",sa.Boolean(),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("providers",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("identity_issuer",sa.String(255),nullable=False),
        sa.Column("identity_subject",sa.String(255),nullable=False),sa.Column("market_code",sa.String(16),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),sa.Column("onboarding_status",sa.String(48),nullable=False),
        sa.Column("display_name",sa.String(160),nullable=False),sa.Column("version",sa.BigInteger(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("identity_issuer","identity_subject",name="uq_provider_identity"))
    op.create_table("services",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("code",sa.String(80),nullable=False,unique=True),
        sa.Column("category",sa.String(80),nullable=False),sa.Column("name_es",sa.String(160),nullable=False),
        sa.Column("name_en",sa.String(160),nullable=False),sa.Column("duration_minutes",sa.Integer(),nullable=False),
        sa.Column("prep_minutes",sa.Integer(),nullable=False),sa.Column("cleanup_minutes",sa.Integer(),nullable=False),
        sa.Column("active",sa.Boolean(),nullable=False))
    op.create_table("provider_services",
        sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("service_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("services.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("status",sa.String(32),nullable=False))
    op.create_table("availability_rules",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id",ondelete="CASCADE"),nullable=False),
        sa.Column("weekday",sa.Integer(),nullable=False),sa.Column("start_minute",sa.Integer(),nullable=False),
        sa.Column("end_minute",sa.Integer(),nullable=False),sa.Column("timezone",sa.String(64),nullable=False),sa.Column("active",sa.Boolean(),nullable=False))
    op.create_table("availability_exceptions",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id",ondelete="CASCADE"),nullable=False),
        sa.Column("starts_at",sa.DateTime(timezone=True),nullable=False),sa.Column("ends_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("exception_type",sa.String(32),nullable=False))
    op.create_table("price_policies",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("market_code",sa.String(16),nullable=False),
        sa.Column("service_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("services.id"),nullable=False),
        sa.Column("version",sa.Integer(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),
        sa.Column("base_price_minor",sa.BigInteger(),nullable=False),sa.Column("travel_fee_minor",sa.BigInteger(),nullable=False),
        sa.Column("tax_bps",sa.Integer(),nullable=False),sa.Column("effective_from",sa.DateTime(timezone=True),nullable=False),
        sa.Column("effective_until",sa.DateTime(timezone=True)),sa.Column("active",sa.Boolean(),nullable=False),
        sa.UniqueConstraint("market_code","service_id","version",name="uq_price_policy_version"))
    op.create_table("quotes",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("customer_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("customers.id"),nullable=False),
        sa.Column("market_code",sa.String(16),nullable=False),sa.Column("address_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("customer_addresses.id"),nullable=False),
        sa.Column("service_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("services.id"),nullable=False),
        sa.Column("price_policy_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("price_policies.id"),nullable=False),
        sa.Column("price_policy_version",sa.Integer(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),
        sa.Column("subtotal_minor",sa.BigInteger(),nullable=False),sa.Column("tax_minor",sa.BigInteger(),nullable=False),
        sa.Column("total_minor",sa.BigInteger(),nullable=False),sa.Column("scheduled_start",sa.DateTime(timezone=True),nullable=False),
        sa.Column("scheduled_end",sa.DateTime(timezone=True),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),sa.Column("snapshot",postgresql.JSONB(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("booking_lines",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id",ondelete="CASCADE"),nullable=False),
        sa.Column("service_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("services.id"),nullable=False),
        sa.Column("service_snapshot",postgresql.JSONB(),nullable=False),sa.Column("amount_minor",sa.BigInteger(),nullable=False))
    op.create_table("dispatch_offers",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id",ondelete="CASCADE"),nullable=False),
        sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id"),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),sa.Column("rank",sa.Integer(),nullable=False),
        sa.Column("score",sa.Numeric(6,5),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("accepted_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("booking_id","provider_id",name="uq_offer_booking_provider"))
    op.create_table("assignments",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id",ondelete="CASCADE"),nullable=False,unique=True),
        sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id"),nullable=False),
        sa.Column("starts_at",sa.DateTime(timezone=True),nullable=False),sa.Column("ends_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.execute("""ALTER TABLE assignments ADD CONSTRAINT assignments_no_provider_overlap
      EXCLUDE USING gist (provider_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)
      WHERE (status IN ('ACTIVE','IN_SERVICE'))""")
    op.create_table("visits",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id",ondelete="CASCADE"),nullable=False,unique=True),
        sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id"),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),sa.Column("pin_hash",sa.String(128),nullable=False),
        sa.Column("arrived_at",sa.DateTime(timezone=True)),sa.Column("started_at",sa.DateTime(timezone=True)),sa.Column("completed_at",sa.DateTime(timezone=True)))
    op.create_table("payment_intents",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id"),nullable=False),
        sa.Column("customer_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("customers.id"),nullable=False),
        sa.Column("provider_code",sa.String(48),nullable=False),sa.Column("external_id",sa.String(255),unique=True),
        sa.Column("status",sa.String(32),nullable=False),sa.Column("amount_minor",sa.BigInteger(),nullable=False),
        sa.Column("currency",sa.String(3),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("memberships",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("customer_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("customers.id"),nullable=False),
        sa.Column("plan_code",sa.String(80),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("started_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("reviews",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id"),nullable=False,unique=True),
        sa.Column("customer_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("customers.id"),nullable=False),
        sa.Column("provider_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("providers.id"),nullable=False),
        sa.Column("rating",sa.Integer(),nullable=False),sa.Column("comment",sa.Text()),sa.Column("status",sa.String(32),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_check_constraint("ck_reviews_rating","reviews","rating BETWEEN 1 AND 5")
    op.create_table("support_cases",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id")),
        sa.Column("requester_subject",sa.String(255),nullable=False),sa.Column("category",sa.String(80),nullable=False),
        sa.Column("subject",sa.String(255),nullable=False),sa.Column("message",sa.Text(),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("safety_incidents",
        sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("booking_id",postgresql.UUID(as_uuid=True),sa.ForeignKey("bookings.id")),
        sa.Column("reporter_subject",sa.String(255),nullable=False),sa.Column("severity",sa.String(2),nullable=False),
        sa.Column("category",sa.String(80),nullable=False),sa.Column("description",sa.Text(),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))

def downgrade():
    for table in ["safety_incidents","support_cases","reviews","memberships","payment_intents","visits","assignments","dispatch_offers","booking_lines","quotes","price_policies","availability_exceptions","availability_rules","provider_services","services","providers","device_registrations","customer_addresses","customers"]:
        op.drop_table(table)
