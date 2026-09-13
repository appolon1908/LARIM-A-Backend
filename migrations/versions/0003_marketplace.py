"""Persistent marketplace aggregates; preserve legacy tables for explicit data migration.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE catalog_services (\n\tcode VARCHAR(80) NOT NULL, \n\tcategory VARCHAR(80) NOT NULL, \n\tname JSON NOT NULL, \n\tmarket_code VARCHAR(16) NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tduration_minutes INTEGER NOT NULL, \n\tbase_minor BIGINT NOT NULL, \n\ttravel_minor BIGINT NOT NULL, \n\ttax_bps INTEGER NOT NULL, \n\tfee_bps INTEGER NOT NULL, \n\trequired_skills JSON NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_catalog_services PRIMARY KEY (id), \n\tCONSTRAINT uq_catalog_services_code UNIQUE (code)\n)"
    )
    op.execute("CREATE INDEX ix_catalog_services_created_at ON catalog_services (created_at)")
    op.execute("CREATE INDEX ix_catalog_services_market_code ON catalog_services (market_code)")
    op.execute(
        "CREATE TABLE marketplace_users (\n\tsubject VARCHAR(255) NOT NULL, \n\temail VARCHAR(255) NOT NULL, \n\tpassword_hash VARCHAR(255), \n\troles JSON NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_users PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_users_subject UNIQUE (subject), \n\tCONSTRAINT uq_marketplace_users_email UNIQUE (email)\n)"
    )
    op.execute("CREATE INDEX ix_marketplace_users_created_at ON marketplace_users (created_at)")
    op.execute(
        "CREATE TABLE customer_addresses (\n\tcustomer_id UUID NOT NULL, \n\tlabel VARCHAR(120) NOT NULL, \n\tlatitude FLOAT NOT NULL, \n\tlongitude FLOAT NOT NULL, \n\tmarket_code VARCHAR(16) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_customer_addresses PRIMARY KEY (id), \n\tCONSTRAINT fk_customer_addresses_customer_id_marketplace_users FOREIGN KEY(customer_id) REFERENCES marketplace_users (id)\n)"
    )
    op.execute("CREATE INDEX ix_customer_addresses_customer_id ON customer_addresses (customer_id)")
    op.execute("CREATE INDEX ix_customer_addresses_created_at ON customer_addresses (created_at)")
    op.execute(
        "CREATE TABLE marketplace_notifications (\n\tevent_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tkind VARCHAR(120) NOT NULL, \n\tpayload JSON NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_notifications PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_notifications_event_id UNIQUE (event_id), \n\tCONSTRAINT fk_marketplace_notifications_event_id_outbox_events FOREIGN KEY(event_id) REFERENCES outbox_events (id), \n\tCONSTRAINT fk_marketplace_notifications_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_notifications_user_id ON marketplace_notifications (user_id)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_notifications_created_at ON marketplace_notifications (created_at)"
    )
    op.execute(
        "CREATE TABLE provider_profiles (\n\tuser_id UUID NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tonline BOOLEAN NOT NULL, \n\tmarket_code VARCHAR(16) NOT NULL, \n\tservices JSON NOT NULL, \n\tskills JSON NOT NULL, \n\tavailability JSON NOT NULL, \n\tlatitude FLOAT NOT NULL, \n\tlongitude FLOAT NOT NULL, \n\tradius_km FLOAT NOT NULL, \n\trating FLOAT NOT NULL, \n\tcompletion_rate FLOAT NOT NULL, \n\tworkload INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_provider_profiles PRIMARY KEY (id), \n\tCONSTRAINT uq_provider_profiles_user_id UNIQUE (user_id), \n\tCONSTRAINT fk_provider_profiles_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id)\n)"
    )
    op.execute("CREATE INDEX ix_provider_profiles_created_at ON provider_profiles (created_at)")
    op.execute("CREATE INDEX ix_provider_profiles_status ON provider_profiles (status)")
    op.execute(
        "CREATE TABLE blocked_relationships (\n\tcustomer_id UUID NOT NULL, \n\tprovider_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_blocked_relationships PRIMARY KEY (id), \n\tCONSTRAINT uq_blocked_relationships_customer_id UNIQUE (customer_id, provider_id), \n\tCONSTRAINT fk_blocked_relationships_customer_id_marketplace_users FOREIGN KEY(customer_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_blocked_relationships_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_blocked_relationships_created_at ON blocked_relationships (created_at)"
    )
    op.execute(
        "CREATE INDEX ix_blocked_relationships_customer_id ON blocked_relationships (customer_id)"
    )
    op.execute(
        "CREATE INDEX ix_blocked_relationships_provider_id ON blocked_relationships (provider_id)"
    )
    op.execute(
        "CREATE TABLE marketplace_quotes (\n\tcustomer_id UUID NOT NULL, \n\tservice_id UUID NOT NULL, \n\taddress_id UUID NOT NULL, \n\tscheduled_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\tscheduled_end TIMESTAMP WITH TIME ZONE NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsnapshot JSON NOT NULL, \n\taccepted BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_quotes PRIMARY KEY (id), \n\tCONSTRAINT fk_marketplace_quotes_customer_id_marketplace_users FOREIGN KEY(customer_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_marketplace_quotes_service_id_catalog_services FOREIGN KEY(service_id) REFERENCES catalog_services (id), \n\tCONSTRAINT fk_marketplace_quotes_address_id_customer_addresses FOREIGN KEY(address_id) REFERENCES customer_addresses (id)\n)"
    )
    op.execute("CREATE INDEX ix_marketplace_quotes_customer_id ON marketplace_quotes (customer_id)")
    op.execute("CREATE INDEX ix_marketplace_quotes_created_at ON marketplace_quotes (created_at)")
    op.execute(
        "CREATE TABLE marketplace_bookings (\n\tquote_id UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tprovider_id UUID, \n\tstatus VARCHAR(32) NOT NULL, \n\tsnapshot JSON NOT NULL, \n\taddress JSON NOT NULL, \n\tscheduled_start TIMESTAMP WITH TIME ZONE NOT NULL, \n\tscheduled_end TIMESTAMP WITH TIME ZONE NOT NULL, \n\tversion INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_bookings PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_bookings_quote_id UNIQUE (quote_id), \n\tCONSTRAINT fk_marketplace_bookings_quote_id_marketplace_quotes FOREIGN KEY(quote_id) REFERENCES marketplace_quotes (id), \n\tCONSTRAINT fk_marketplace_bookings_customer_id_marketplace_users FOREIGN KEY(customer_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_marketplace_bookings_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id)\n)"
    )
    op.execute("CREATE INDEX ix_marketplace_bookings_status ON marketplace_bookings (status)")
    op.execute(
        "CREATE INDEX ix_marketplace_bookings_provider_id ON marketplace_bookings (provider_id)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_bookings_customer_id ON marketplace_bookings (customer_id)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_bookings_created_at ON marketplace_bookings (created_at)"
    )
    op.execute(
        "CREATE TABLE booking_status_history (\n\tbooking_id UUID NOT NULL, \n\tactor VARCHAR(255) NOT NULL, \n\tprevious VARCHAR(32) NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_booking_status_history PRIMARY KEY (id), \n\tCONSTRAINT fk_booking_status_history_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_booking_status_history_created_at ON booking_status_history (created_at)"
    )
    op.execute(
        "CREATE INDEX ix_booking_status_history_booking_id ON booking_status_history (booking_id)"
    )
    op.execute(
        "CREATE TABLE dispatch_offers (\n\tbooking_id UUID NOT NULL, \n\tprovider_id UUID NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trank_score FLOAT NOT NULL, \n\tattempt INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_dispatch_offers PRIMARY KEY (id), \n\tCONSTRAINT uq_dispatch_offers_booking_id UNIQUE (booking_id, provider_id, attempt), \n\tCONSTRAINT fk_dispatch_offers_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT fk_dispatch_offers_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id)\n)"
    )
    op.execute("CREATE INDEX ix_dispatch_offers_provider_id ON dispatch_offers (provider_id)")
    op.execute("CREATE INDEX ix_dispatch_offers_created_at ON dispatch_offers (created_at)")
    op.execute("CREATE INDEX ix_dispatch_offers_status ON dispatch_offers (status)")
    op.execute("CREATE INDEX ix_dispatch_offers_booking_id ON dispatch_offers (booking_id)")
    op.execute("CREATE INDEX ix_dispatch_offers_expires_at ON dispatch_offers (expires_at)")
    op.execute(
        "CREATE TABLE marketplace_cases (\n\towner_id UUID NOT NULL, \n\tbooking_id UUID, \n\tkind VARCHAR(24) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tbody VARCHAR(4000) NOT NULL, \n\tresolution VARCHAR(4000), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_cases PRIMARY KEY (id), \n\tCONSTRAINT fk_marketplace_cases_owner_id_marketplace_users FOREIGN KEY(owner_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_marketplace_cases_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id)\n)"
    )
    op.execute("CREATE INDEX ix_marketplace_cases_owner_id ON marketplace_cases (owner_id)")
    op.execute("CREATE INDEX ix_marketplace_cases_created_at ON marketplace_cases (created_at)")
    op.execute("CREATE INDEX ix_marketplace_cases_status ON marketplace_cases (status)")
    op.execute("CREATE INDEX ix_marketplace_cases_kind ON marketplace_cases (kind)")
    op.execute(
        "CREATE TABLE marketplace_payments (\n\tbooking_id UUID NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\texternal_reference VARCHAR(255) NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\trefunded_minor BIGINT NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_payments PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_payments_booking_id UNIQUE (booking_id), \n\tCONSTRAINT fk_marketplace_payments_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT uq_marketplace_payments_external_reference UNIQUE (external_reference)\n)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_payments_created_at ON marketplace_payments (created_at)"
    )
    op.execute(
        "CREATE TABLE marketplace_reviews (\n\tbooking_id UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tprovider_id UUID NOT NULL, \n\trating INTEGER NOT NULL, \n\tbody VARCHAR(2000) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_reviews PRIMARY KEY (id), \n\tCONSTRAINT uq_marketplace_reviews_booking_id UNIQUE (booking_id), \n\tCONSTRAINT fk_marketplace_reviews_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT fk_marketplace_reviews_customer_id_marketplace_users FOREIGN KEY(customer_id) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_marketplace_reviews_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_marketplace_reviews_provider_id ON marketplace_reviews (provider_id)"
    )
    op.execute("CREATE INDEX ix_marketplace_reviews_created_at ON marketplace_reviews (created_at)")
    op.execute(
        "CREATE TABLE provider_earnings (\n\tbooking_id UUID NOT NULL, \n\tprovider_id UUID NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_provider_earnings PRIMARY KEY (id), \n\tCONSTRAINT uq_provider_earnings_booking_id UNIQUE (booking_id), \n\tCONSTRAINT fk_provider_earnings_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT fk_provider_earnings_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id)\n)"
    )
    op.execute("CREATE INDEX ix_provider_earnings_status ON provider_earnings (status)")
    op.execute("CREATE INDEX ix_provider_earnings_created_at ON provider_earnings (created_at)")
    op.execute("CREATE INDEX ix_provider_earnings_provider_id ON provider_earnings (provider_id)")
    op.execute(
        "CREATE TABLE marketplace_refunds (\n\tpayment_id UUID NOT NULL, \n\tamount_minor BIGINT NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\texternal_reference VARCHAR(255) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_marketplace_refunds PRIMARY KEY (id), \n\tCONSTRAINT fk_marketplace_refunds_payment_id_marketplace_payments FOREIGN KEY(payment_id) REFERENCES marketplace_payments (id), \n\tCONSTRAINT uq_marketplace_refunds_external_reference UNIQUE (external_reference)\n)"
    )
    op.execute("CREATE INDEX ix_marketplace_refunds_payment_id ON marketplace_refunds (payment_id)")
    op.execute("CREATE INDEX ix_marketplace_refunds_created_at ON marketplace_refunds (created_at)")


def downgrade():
    raise RuntimeError(
        "Marketplace downgrade requires an explicit data export and reviewed recovery plan"
    )
