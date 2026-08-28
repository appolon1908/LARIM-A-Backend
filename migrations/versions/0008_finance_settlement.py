"""financial ledger, reconciliation, provider payables and payout controls

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ledger_accounts",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "ledger_transactions",
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="POSTED",
        ),
    )
    op.add_column(
        "ledger_transactions",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "ledger_transactions",
        sa.Column(
            "posted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_ledger_transaction_reference",
        "ledger_transactions",
        ["reference_type", "reference_id"],
    )
    op.create_check_constraint(
        "ck_ledger_transactions_status",
        "ledger_transactions",
        "status = 'POSTED'",
    )

    op.execute(
        """
        INSERT INTO ledger_accounts (id, code, account_type, currency, active)
        VALUES
          ('9d484ed4-c0aa-5df4-a831-2b22ca90c750',
           'PROCESSOR_CLEARING:DOP', 'ASSET', 'DOP', true),
          ('d1a91b00-2f73-55eb-bfd9-1f5840847c6a',
           'PROVIDER_PAYABLE:DOP', 'LIABILITY', 'DOP', true),
          ('4abc630e-8b70-5884-b078-eddf59ba409b',
           'PLATFORM_REVENUE:DOP', 'REVENUE', 'DOP', true),
          ('b0c9ba4c-fc04-5007-92a6-653e163077f7',
           'TAX_PAYABLE:DOP', 'LIABILITY', 'DOP', true)
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE FUNCTION larimia_prevent_ledger_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'posted ledger records are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER ledger_transactions_immutable
        BEFORE UPDATE OR DELETE ON ledger_transactions
        FOR EACH ROW EXECUTE FUNCTION larimia_prevent_ledger_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION larimia_prevent_ledger_mutation()
        """
    )

    op.create_table(
        "financial_adjustment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by_subject", sa.String(255), nullable=False),
        sa.Column("approved_by_subject", sa.String(255)),
        sa.Column("rejected_by_subject", sa.String(255)),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="PENDING_SECOND_APPROVAL",
        ),
        sa.Column(
            "debit_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "credit_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_accounts.id"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "ledger_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ledger_transactions.id"),
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "debit_account_id <> credit_account_id",
            name="ck_financial_adjustment_requests_financial_adjustment_accounts_different",
        ),
        sa.CheckConstraint(
            "amount_minor > 0",
            name="ck_financial_adjustment_requests_financial_adjustment_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_SECOND_APPROVAL','POSTED','REJECTED')",
            name="ck_financial_adjustment_requests_status",
        ),
    )
    op.create_index(
        "ix_financial_adjustment_requests_requested_by_subject",
        "financial_adjustment_requests",
        ["requested_by_subject"],
    )
    op.create_index(
        "ix_financial_adjustment_requests_status",
        "financial_adjustment_requests",
        ["status"],
    )

    op.create_table(
        "reconciliation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="REQUESTED"),
        sa.Column("requested_by_subject", sa.String(255), nullable=False),
        sa.Column("source_reference", sa.String(255)),
        sa.Column("records_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("break_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "period_start < period_end",
            name="ck_reconciliation_runs_reconciliation_period_valid",
        ),
        sa.CheckConstraint(
            "records_scanned >= 0 AND records_matched >= 0 AND break_count >= 0",
            name="ck_reconciliation_runs_reconciliation_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('REQUESTED','RUNNING','COMPLETED','FAILED')",
            name="ck_reconciliation_runs_status",
        ),
    )
    op.create_index(
        "ix_reconciliation_runs_provider_code",
        "reconciliation_runs",
        ["provider_code"],
    )
    op.create_index(
        "ix_reconciliation_runs_status",
        "reconciliation_runs",
        ["status"],
    )

    op.create_table(
        "reconciliation_breaks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reconciliation_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("provider_code", sa.String(80), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=False),
        sa.Column("break_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("currency", sa.String(3)),
        sa.Column("expected_minor", sa.BigInteger()),
        sa.Column("actual_minor", sa.BigInteger()),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text()),
        sa.Column("resolved_by_subject", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "provider_code",
            "external_reference",
            "break_type",
            name="uq_reconciliation_break_identity",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','RESOLVED','IGNORED')",
            name="ck_reconciliation_breaks_status",
        ),
    )
    op.create_index(
        "ix_reconciliation_breaks_run_id",
        "reconciliation_breaks",
        ["run_id"],
    )
    op.create_index(
        "ix_reconciliation_breaks_provider_code",
        "reconciliation_breaks",
        ["provider_code"],
    )

    op.create_table(
        "provider_payables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id"),
            nullable=False,
        ),
        sa.Column(
            "booking_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bookings.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "payment_intent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_intents.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("service_subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("platform_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("net_minor", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hold_reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "service_subtotal_minor >= 0 AND platform_fee_minor >= 0",
            name="ck_provider_payables_provider_payable_components_nonnegative",
        ),
        sa.CheckConstraint(
            "net_minor >= 0",
            name="ck_provider_payables_provider_payable_net_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','AVAILABLE','RESERVED','HELD','PAID','REVERSED')",
            name="ck_provider_payables_status",
        ),
    )
    op.create_index(
        "ix_provider_payables_provider_id",
        "provider_payables",
        ["provider_id"],
    )
    op.create_index(
        "ix_provider_payables_status",
        "provider_payables",
        ["status"],
    )

    op.create_table(
        "payout_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("external_account_reference", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(48), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("last4", sa.String(4)),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="PENDING_VERIFICATION",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider_id",
            "provider_code",
            "external_account_reference",
            name="uq_payout_account_provider_reference",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_VERIFICATION','VERIFIED','RESTRICTED','DISABLED')",
            name="ck_payout_accounts_status",
        ),
    )
    op.create_index(
        "ix_payout_accounts_provider_id",
        "payout_accounts",
        ["provider_id"],
    )
    op.create_index(
        "uq_payout_accounts_active_provider",
        "payout_accounts",
        ["provider_id", "provider_code"],
        unique=True,
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "payout_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_number", sa.String(64), nullable=False, unique=True),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="PENDING_APPROVAL",
        ),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("requested_by_subject", sa.String(255), nullable=False),
        sa.Column("approved_by_subject", sa.String(255)),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "total_minor > 0",
            name="ck_payout_batches_payout_batch_total_positive",
        ),
        sa.CheckConstraint(
            "item_count > 0",
            name="ck_payout_batches_payout_batch_item_count_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPROVED','PROCESSING','COMPLETED','FAILED','CANCELLED')",
            name="ck_payout_batches_status",
        ),
    )
    op.create_index(
        "ix_payout_batches_status",
        "payout_batches",
        ["status"],
    )

    op.create_table(
        "payout_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payout_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "payable_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_payables.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "provider_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("providers.id"),
            nullable=False,
        ),
        sa.Column(
            "payout_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payout_accounts.id"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("external_payout_id", sa.String(255), unique=True),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0",
            name="ck_payout_items_payout_item_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','SUBMITTED','PAID','FAILED','REVERSED','CANCELLED')",
            name="ck_payout_items_status",
        ),
    )
    op.create_index("ix_payout_items_batch_id", "payout_items", ["batch_id"])
    op.create_index("ix_payout_items_provider_id", "payout_items", ["provider_id"])


def downgrade() -> None:
    for table in [
        "payout_items",
        "payout_batches",
        "payout_accounts",
        "provider_payables",
        "reconciliation_breaks",
        "reconciliation_runs",
        "financial_adjustment_requests",
    ]:
        op.drop_table(table)

    op.execute("DROP TRIGGER IF EXISTS ledger_entries_immutable ON ledger_entries")
    op.execute(
        "DROP TRIGGER IF EXISTS ledger_transactions_immutable ON ledger_transactions"
    )
    op.execute("DROP FUNCTION IF EXISTS larimia_prevent_ledger_mutation()")

    op.execute(
        """
        DELETE FROM ledger_accounts
        WHERE code IN (
          'PROCESSOR_CLEARING:DOP',
          'PROVIDER_PAYABLE:DOP',
          'PLATFORM_REVENUE:DOP',
          'TAX_PAYABLE:DOP'
        )
        AND NOT EXISTS (
          SELECT 1
          FROM ledger_entries
          WHERE ledger_entries.account_id = ledger_accounts.id
        )
        """
    )
    op.drop_constraint(
        "ck_ledger_transactions_status",
        "ledger_transactions",
        type_="check",
    )
    op.drop_constraint(
        "uq_ledger_transaction_reference",
        "ledger_transactions",
        type_="unique",
    )
    for column in ["posted_at", "metadata_json", "status"]:
        op.drop_column("ledger_transactions", column)
    op.drop_column("ledger_accounts", "active")
