from alembic import context
from sqlalchemy import engine_from_config, pool

from larimia.bookings.infrastructure.models import Booking  # noqa: F401
from larimia.commerce import models as commerce_models  # noqa: F401
from larimia.config import get_settings
from larimia.integrations.models import IntegrationStatus  # noqa: F401
from larimia.ledger.infrastructure_models import (  # noqa: F401
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from larimia.marketplace import models as marketplace_models  # noqa: F401
from larimia.marketplace.capacity import CapacityHold  # noqa: F401
from larimia.payments import models as payment_models  # noqa: F401
from larimia.shared.audit import AuditEvent  # noqa: F401
from larimia.shared.db import Base
from larimia.shared.events import InboxReceipt, OutboxEvent  # noqa: F401
from larimia.shared.idempotency_models import IdempotencyRecord  # noqa: F401

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section) or {}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
