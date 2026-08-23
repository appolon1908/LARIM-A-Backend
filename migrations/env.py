from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

from larimia.shared.db import Base
from larimia.bookings.infrastructure.models import Booking
from larimia.shared.audit import AuditEvent
from larimia.shared.events import OutboxEvent, InboxReceipt
from larimia.ledger.infrastructure_models import LedgerAccount, LedgerTransaction, LedgerEntry

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

from larimia.shared.idempotency_models import IdempotencyRecord
from larimia.integrations.models import IntegrationStatus
