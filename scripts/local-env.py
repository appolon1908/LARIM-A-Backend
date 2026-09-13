"""Create random local credentials; refuse to overwrite a developer's existing file."""

import os
import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    raise SystemExit(".env already exists; retain current credentials")
password = secrets.token_urlsafe(32)
values = {
    "LARIMIA_DB_PASSWORD": password,
    "LARIMIA_DATABASE_URL": f"postgresql+psycopg://larimia:{password}@postgres:5432/larimia",
    "LARIMIA_REDIS_URL": "redis://redis:6379/0",
    "LARIMIA_ENV": "development",
    "LARIMIA_AUTH_MODE": "local",
    "LARIMIA_NOTIFICATION_MODE": "local",
    "LARIMIA_LOCAL_JWT_SECRET": secrets.token_urlsafe(48),
    "LARIMIA_SEED_PASSWORD": secrets.token_urlsafe(24),
}
with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
    f.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
print("Created protected .env with random local credentials; values are not logged.")
