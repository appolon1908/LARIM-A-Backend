"""Durable notification templates, preferences and leased channel delivery."""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE notification_preferences (\n\tuser_id UUID NOT NULL, \n\tchannels JSON NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_notification_preferences PRIMARY KEY (id), \n\tCONSTRAINT uq_notification_preferences_user_id UNIQUE (user_id), \n\tCONSTRAINT fk_notification_preferences_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_notification_preferences_created_at ON notification_preferences (created_at)"
    )
    op.execute(
        "\nCREATE TABLE notification_templates (\n\tevent_type VARCHAR(120) NOT NULL, \n\tchannel VARCHAR(16) NOT NULL, \n\tsubject VARCHAR(200) NOT NULL, \n\tbody VARCHAR(4000) NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_notification_templates PRIMARY KEY (id), \n\tCONSTRAINT uq_notification_templates_event_type UNIQUE (event_type, channel)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_notification_templates_created_at ON notification_templates (created_at)"
    )
    op.execute(
        "\nCREATE TABLE notification_deliveries (\n\tnotification_id UUID NOT NULL, \n\tuser_id UUID NOT NULL, \n\tchannel VARCHAR(16) NOT NULL, \n\ttemplate_version INTEGER NOT NULL, \n\tsubject VARCHAR(500) NOT NULL, \n\tbody VARCHAR(8000) NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_token VARCHAR(36), \n\tlast_error VARCHAR(120), \n\tprovider_reference VARCHAR(200), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_notification_deliveries PRIMARY KEY (id), \n\tCONSTRAINT uq_notification_deliveries_notification_id UNIQUE (notification_id, channel), \n\tCONSTRAINT fk_notification_deliveries_notification_id_marketplace__e372 FOREIGN KEY(notification_id) REFERENCES marketplace_notifications (id), \n\tCONSTRAINT fk_notification_deliveries_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_notification_deliveries_created_at ON notification_deliveries (created_at)"
    )
    op.execute(
        "CREATE INDEX ix_notification_deliveries_notification_id ON notification_deliveries (notification_id)"
    )
    op.execute("CREATE INDEX ix_notification_deliveries_status ON notification_deliveries (status)")
    op.execute(
        "CREATE INDEX ix_notification_deliveries_user_id ON notification_deliveries (user_id)"
    )
    op.execute(
        "CREATE INDEX ix_notification_delivery_due ON notification_deliveries(status, available_at)"
    )
    op.execute("ALTER TABLE marketplace_notifications ADD COLUMN external_enqueued_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX ix_notification_fanout ON marketplace_notifications(created_at, id) WHERE external_enqueued_at IS NULL"
    )


def downgrade():
    raise RuntimeError("Drain and export notification deliveries before reviewed rollback")
