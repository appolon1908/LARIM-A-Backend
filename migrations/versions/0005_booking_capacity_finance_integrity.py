"""booking capacity and financial integrity

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing installations must reconcile orphan rows before this migration can pass.
    op.execute(
        """
        ALTER TABLE bookings
        ADD CONSTRAINT fk_bookings_customer_id_customers
        FOREIGN KEY (customer_id) REFERENCES customers(id) NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE bookings VALIDATE CONSTRAINT fk_bookings_customer_id_customers"
    )

    op.execute(
        """
        ALTER TABLE ledger_entries
        ADD CONSTRAINT fk_ledger_entries_transaction_id_ledger_transactions
        FOREIGN KEY (transaction_id) REFERENCES ledger_transactions(id) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE ledger_entries
        ADD CONSTRAINT fk_ledger_entries_account_id_ledger_accounts
        FOREIGN KEY (account_id) REFERENCES ledger_accounts(id) NOT VALID
        """
    )
    op.execute(
        """
        ALTER TABLE ledger_entries
        VALIDATE CONSTRAINT fk_ledger_entries_transaction_id_ledger_transactions
        """
    )
    op.execute(
        """
        ALTER TABLE ledger_entries
        VALIDATE CONSTRAINT fk_ledger_entries_account_id_ledger_accounts
        """
    )
    op.create_check_constraint(
        "ck_ledger_entries_direction",
        "ledger_entries",
        "direction IN ('DEBIT', 'CREDIT')",
    )
    op.create_check_constraint(
        "ck_ledger_entries_amount_positive",
        "ledger_entries",
        "amount_minor > 0",
    )

    op.add_column(
        "idempotency_records",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "idempotency_records",
        sa.Column("locked_until", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "idempotency_records",
        sa.Column("last_error", sa.Text()),
    )
    op.create_index(
        "ix_idempotency_processing_lease",
        "idempotency_records",
        ["status", "locked_until"],
    )

    op.create_table(
        "capacity_holds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("quotes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id"),
            nullable=False,
        ),
        sa.Column("market_code", sa.String(16), nullable=False),
        sa.Column(
            "service_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("services.id"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="ACTIVE"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "consumed_by_booking_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookings.id"),
            unique=True,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("quantity > 0", name="ck_capacity_holds_quantity_positive"),
        sa.CheckConstraint("starts_at < ends_at", name="ck_capacity_holds_valid_window"),
        sa.CheckConstraint(
            "status IN ('ACTIVE','CONSUMED','EXPIRED','RELEASED','INVALIDATED')",
            name="ck_capacity_holds_status",
        ),
    )
    op.create_index(
        "ix_capacity_holds_ready",
        "capacity_holds",
        ["market_code", "service_id", "status", "expires_at"],
    )
    op.create_index(
        "ix_capacity_holds_window",
        "capacity_holds",
        ["starts_at", "ends_at"],
    )

    op.add_column(
        "bookings",
        sa.Column("quote_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "bookings",
        sa.Column("capacity_hold_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "bookings",
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "bookings",
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "bookings",
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "bookings",
        sa.Column("cancellation_reason", sa.String(255)),
    )
    op.create_foreign_key(
        "fk_bookings_quote_id_quotes",
        "bookings",
        "quotes",
        ["quote_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_bookings_capacity_hold_id_capacity_holds",
        "bookings",
        "capacity_holds",
        ["capacity_hold_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_bookings_payment_intent_id_payment_intents",
        "bookings",
        "payment_intents",
        ["payment_intent_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_bookings_quote_id",
        "bookings",
        ["quote_id"],
    )
    op.create_unique_constraint(
        "uq_bookings_capacity_hold_id",
        "bookings",
        ["capacity_hold_id"],
    )
    op.create_unique_constraint(
        "uq_bookings_payment_intent_id",
        "bookings",
        ["payment_intent_id"],
    )
    op.create_index(
        "ix_payment_intents_booking_status",
        "payment_intents",
        ["booking_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_intents_booking_status",
        table_name="payment_intents",
    )
    op.drop_constraint(
        "uq_bookings_payment_intent_id",
        "bookings",
        type_="unique",
    )
    op.drop_constraint(
        "uq_bookings_capacity_hold_id",
        "bookings",
        type_="unique",
    )
    op.drop_constraint(
        "uq_bookings_quote_id",
        "bookings",
        type_="unique",
    )
    op.drop_constraint(
        "fk_bookings_payment_intent_id_payment_intents",
        "bookings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bookings_capacity_hold_id_capacity_holds",
        "bookings",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bookings_quote_id_quotes",
        "bookings",
        type_="foreignkey",
    )
    for column in [
        "cancellation_reason",
        "cancelled_at",
        "confirmed_at",
        "payment_intent_id",
        "capacity_hold_id",
        "quote_id",
    ]:
        op.drop_column("bookings", column)

    op.drop_index("ix_capacity_holds_window", table_name="capacity_holds")
    op.drop_index("ix_capacity_holds_ready", table_name="capacity_holds")
    op.drop_table("capacity_holds")

    op.drop_index(
        "ix_idempotency_processing_lease",
        table_name="idempotency_records",
    )
    for column in ["last_error", "locked_until", "updated_at"]:
        op.drop_column("idempotency_records", column)

    op.drop_constraint(
        "ck_ledger_entries_amount_positive",
        "ledger_entries",
        type_="check",
    )
    op.drop_constraint(
        "ck_ledger_entries_direction",
        "ledger_entries",
        type_="check",
    )
    op.drop_constraint(
        "fk_ledger_entries_account_id_ledger_accounts",
        "ledger_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_ledger_entries_transaction_id_ledger_transactions",
        "ledger_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bookings_customer_id_customers",
        "bookings",
        type_="foreignkey",
    )
