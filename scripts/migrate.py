"""Migrate with a separate identity, then provision the bounded runtime database role."""

from alembic import command
from alembic.config import Config
from psycopg import connect, sql
from sqlalchemy.engine import make_url

from larimia.config import get_settings

settings = get_settings()
command.upgrade(Config("alembic.ini"), "head")
if settings.runtime_database_url:
    runtime = make_url(settings.runtime_database_url)
    migrator = make_url(settings.database_url)
    if (
        runtime.username != "larimia_app"
        or runtime.database != migrator.database
        or runtime.host != migrator.host
        or not runtime.password
    ):
        raise RuntimeError("Runtime identity must be larimia_app in the migrated database")
    # No SQL statement logging; psycopg composition quotes the generated password safely.
    with connect(settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)) as db:
        if not db.execute("SELECT 1 FROM pg_roles WHERE rolname='larimia_app'").fetchone():
            db.execute(
                sql.SQL("CREATE ROLE larimia_app LOGIN PASSWORD {}").format(
                    sql.Literal(runtime.password)
                )
            )
        else:
            db.execute(
                sql.SQL("ALTER ROLE larimia_app LOGIN PASSWORD {}").format(
                    sql.Literal(runtime.password)
                )
            )
        db.execute("ALTER ROLE larimia_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION")
        db.execute("GRANT USAGE ON SCHEMA public TO larimia_app")
        db.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO larimia_app")
        db.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO larimia_app")
        db.execute(
            "REVOKE UPDATE ON ledger_entries, ledger_transactions, audit_events, "
            "booking_status_history FROM larimia_app"
        )
        db.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
command.current(Config("alembic.ini"))
print("Migration and runtime-role provisioning completed; credentials were not logged.")
