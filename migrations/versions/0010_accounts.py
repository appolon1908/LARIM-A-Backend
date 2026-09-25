"""Owned profiles, preferences and revocable device-bound sessions."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE account_profiles (\n\tuser_id UUID NOT NULL, \n\tdisplay_name VARCHAR(120) NOT NULL, \n\tlocale VARCHAR(35) NOT NULL, \n\ttimezone VARCHAR(100) NOT NULL, \n\tpreferences JSON NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_account_profiles PRIMARY KEY (id), \n\tCONSTRAINT uq_account_profiles_user_id UNIQUE (user_id), \n\tCONSTRAINT fk_account_profiles_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_account_profiles_created_at ON account_profiles (created_at)")
    op.execute(
        "\nCREATE TABLE account_devices (\n\tuser_id UUID NOT NULL, \n\tlabel VARCHAR(80) NOT NULL, \n\tplatform VARCHAR(16) NOT NULL, \n\trevoked BOOLEAN NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tCONSTRAINT pk_account_devices PRIMARY KEY (id), \n\tCONSTRAINT fk_account_devices_user_id_marketplace_users FOREIGN KEY(user_id) REFERENCES marketplace_users (id)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_account_devices_created_at ON account_devices (created_at)")
    op.execute("CREATE INDEX ix_account_devices_user_id ON account_devices (user_id)")
    op.execute(
        "ALTER TABLE refresh_sessions ADD COLUMN device_id UUID REFERENCES account_devices(id)"
    )
    op.execute("CREATE INDEX ix_refresh_sessions_device_id ON refresh_sessions(device_id)")


def downgrade():
    raise RuntimeError("Preserve account session revocation history during rollback")
