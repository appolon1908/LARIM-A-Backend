"""Communications, payouts, documents and financial invariants."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE marketplace_promotions (\n\tcode VARCHAR(80) NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_promotions PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_promotions_code UNIQUE (code)\n)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_promotions_created_at ON marketplace_promotions (created_at)"
    )
    op.execute(
        "CREATE TABLE refresh_sessions (\n\tuser_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_refresh_sessions PRIMARY KEY (id), \n\tCONSTRAINT fk_refresh_sessions_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT uq_refresh_sessions_token_hash UNIQUE (token_hash)\n)"
    )
    op.execute("CREATE INDEX ix_refresh_sessions_user_id ON refresh_sessions (user_id)")
    op.execute("CREATE INDEX ix_refresh_sessions_created_at ON refresh_sessions (created_at)")
    op.execute(
        "CREATE TABLE marketplace_payouts (\n\tprovider_id UUID NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tearning_ids JSON NOT NULL, \n\tapproved_by VARCHAR(255) NOT NULL, \n\texternal_reference VARCHAR(255), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_payouts PRIMARY KEY (id), \n\tCONSTRAINT fk_marketplace_payouts_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id), \n\tCONSTRAINT uq_marketplace_payouts_external_reference UNIQUE (external_reference)\n)"
    )
    op.execute("CREATE INDEX ix_marketplace_payouts_status ON marketplace_payouts (status)")
    op.execute(
        "CREATE INDEX ix_marketplace_payouts_provider_id ON marketplace_payouts (provider_id)"
    )
    op.execute("CREATE INDEX ix_marketplace_payouts_created_at ON marketplace_payouts (created_at)")
    op.execute(
        "CREATE TABLE marketplace_conversations (\n\tbooking_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_conversations PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_conversations_booking_id UNIQUE (booking_id), \n\tCONSTRAINT fk_marketplace_conversations_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_conversations_created_at ON marketplace_conversations (created_at)"
    )
    op.execute(
        "CREATE TABLE private_documents (\n\towner_id UUID NOT NULL, \n\tbooking_id UUID, \n\tstorage_key VARCHAR(255) NOT NULL, \n\tcontent_type VARCHAR(80) NOT NULL, \n\tsize INTEGER NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_private_documents PRIMARY KEY (id), \n\tCONSTRAINT fk_private_documents_owner_id_marketplace_users FOREIGN KEY(owner_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_private_documents_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT uq_private_documents_storage_key UNIQUE (storage_key)\n)"
    )
    op.execute("CREATE INDEX ix_private_documents_booking_id ON private_documents (booking_id)")
    op.execute("CREATE INDEX ix_private_documents_created_at ON private_documents (created_at)")
    op.execute("CREATE INDEX ix_private_documents_owner_id ON private_documents (owner_id)")
    op.execute(
        "CREATE TABLE conversation_messages (\n\tconversation_id UUID NOT NULL, \n\tsender_id UUID NOT NULL, \n\tbody VARCHAR(4000) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_conversation_messages PRIMARY KEY (id), \n\tCONSTRAINT fk_conversation_messages_conversation_id_marketplace_co_d205 FOREIGN KEY(conversation_id) REFERENCES marketplace_conversations (id), \n\tCONSTRAINT fk_conversation_messages_sender_id_marketplace_users FOREIGN KEY(sender_id) REFERENCES marketplace_users (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_conversation_messages_created_at ON conversation_messages (created_at)"
    )
    op.execute(
        "CREATE INDEX ix_conversation_messages_conversation_id ON conversation_messages (conversation_id)"
    )
    op.execute(
        "ALTER TABLE ledger_entries ADD CONSTRAINT fk_journal_transaction FOREIGN KEY (transaction_id) REFERENCES ledger_transactions(id)"
    )
    op.execute(
        "ALTER TABLE ledger_entries ADD CONSTRAINT fk_journal_account FOREIGN KEY (account_id) REFERENCES ledger_accounts(id)"
    )
    op.execute(
        "ALTER TABLE ledger_entries ADD CONSTRAINT ck_journal_positive CHECK (amount_minor > 0 AND direction IN ('DEBIT','CREDIT'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_journal_reference ON ledger_transactions(reference_type, reference_id)"
    )
    op.execute(
        "CREATE INDEX ix_offers_provider_pending ON dispatch_offers(provider_id, status, expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_booking_customer_status ON marketplace_bookings(customer_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_booking_provider_status ON marketplace_bookings(provider_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_address_geography ON customer_addresses USING gist ((ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography))"
    )
    op.execute(
        "CREATE INDEX ix_provider_geography ON provider_profiles USING gist ((ST_SetSRID(ST_MakePoint(longitude, latitude),4326)::geography))"
    )
    op.execute(
        "ALTER TABLE marketplace_payments ADD CONSTRAINT ck_payment_amounts CHECK (amount_minor > 0 AND refunded_minor >= 0 AND refunded_minor <= amount_minor)"
    )
    op.execute(
        "ALTER TABLE provider_earnings ADD CONSTRAINT ck_earning_nonnegative CHECK (amount_minor >= 0)"
    )
    op.execute(
        "ALTER TABLE marketplace_reviews ADD CONSTRAINT ck_review_rating CHECK (rating BETWEEN 1 AND 5)"
    )
    op.execute("""
      CREATE FUNCTION larimia_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN RAISE EXCEPTION 'Append-only record cannot be changed'; END $$;
    """)
    for table in (
        "ledger_entries",
        "ledger_transactions",
        "audit_events",
        "booking_status_history",
    ):
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION larimia_immutable()"
        )
    op.execute("""
      CREATE FUNCTION larimia_journal_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE entry_count integer; net bigint; currencies integer; mismatches integer;
      BEGIN
        SELECT count(*), COALESCE(sum(CASE WHEN direction='DEBIT' THEN amount_minor ELSE -amount_minor END),0), count(DISTINCT currency)
          INTO entry_count, net, currencies FROM ledger_entries WHERE transaction_id=NEW.transaction_id;
        SELECT count(*) INTO mismatches FROM ledger_entries e JOIN ledger_accounts a ON a.id=e.account_id
          WHERE e.transaction_id=NEW.transaction_id AND e.currency<>a.currency;
        IF entry_count < 2 OR net <> 0 OR currencies <> 1 OR mismatches <> 0 THEN
          RAISE EXCEPTION 'Unbalanced or mixed currency ledger transaction';
        END IF;
        RETURN NULL;
      END $$;
      CREATE CONSTRAINT TRIGGER journal_balance AFTER INSERT ON ledger_entries
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION larimia_journal_balanced();
    """)


def downgrade():
    raise RuntimeError(
        "Financial records require reviewed forward recovery; destructive downgrade disabled"
    )
