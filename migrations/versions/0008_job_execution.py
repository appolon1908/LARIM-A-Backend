"""Immutable job policy snapshots, checklist evidence and server clock entries."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE service_job_policies (\n\tservice_id UUID NOT NULL, \n\trequirements JSON NOT NULL, \n\tversion INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_service_job_policies PRIMARY KEY (id), \n\tCONSTRAINT uq_service_job_policies_service_id UNIQUE (service_id), \n\tCONSTRAINT fk_service_job_policies_service_id_catalog_services FOREIGN KEY(service_id) REFERENCES catalog_services (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_service_job_policies_created_at ON service_job_policies (created_at)"
    )
    op.execute(
        "\nCREATE TABLE job_checklist_items (\n\tbooking_id UUID NOT NULL, \n\tcode VARCHAR(80) NOT NULL, \n\tcompleted BOOLEAN NOT NULL, \n\tcompleted_by UUID NOT NULL, \n\tevidence_id UUID, \n\tnotes VARCHAR(2000) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_job_checklist_items PRIMARY KEY (id), \n\tCONSTRAINT uq_job_checklist_items_booking_id UNIQUE (booking_id, code), \n\tCONSTRAINT fk_job_checklist_items_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT fk_job_checklist_items_completed_by_marketplace_users FOREIGN KEY(completed_by) REFERENCES marketplace_users (id), \n\tCONSTRAINT fk_job_checklist_items_evidence_id_private_documents FOREIGN KEY(evidence_id) REFERENCES private_documents (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_job_checklist_items_booking_id ON job_checklist_items (booking_id)")
    op.execute("CREATE INDEX ix_job_checklist_items_created_at ON job_checklist_items (created_at)")
    op.execute(
        "\nCREATE TABLE job_time_entries (\n\tbooking_id UUID NOT NULL, \n\tprovider_id UUID NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tended_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_job_time_entries PRIMARY KEY (id), \n\tCONSTRAINT fk_job_time_entries_booking_id_marketplace_bookings FOREIGN KEY(booking_id) REFERENCES marketplace_bookings (id), \n\tCONSTRAINT fk_job_time_entries_provider_id_provider_profiles FOREIGN KEY(provider_id) REFERENCES provider_profiles (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_job_time_entries_booking_id ON job_time_entries (booking_id)")
    op.execute("CREATE INDEX ix_job_time_entries_created_at ON job_time_entries (created_at)")
    op.execute("CREATE INDEX ix_job_time_entries_provider_id ON job_time_entries (provider_id)")
    op.execute(
        "CREATE UNIQUE INDEX ix_job_one_open_clock ON job_time_entries(booking_id) WHERE ended_at IS NULL"
    )
    op.execute(
        "ALTER TABLE job_time_entries ADD CONSTRAINT ck_job_time_order CHECK (ended_at IS NULL OR ended_at >= started_at)"
    )


def downgrade():
    raise RuntimeError("Export job evidence and time records before reviewed rollback")
