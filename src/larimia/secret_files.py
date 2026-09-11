"""Read runtime secret files without copying their values into the environment."""

import os
import stat
from pathlib import Path

MAX_SECRET_BYTES = 65536


def read_secret_file(path: str, name: str) -> str:
    """Read one private regular UTF-8 file; never include its contents in errors."""
    try:
        if not Path(path).is_absolute():
            raise ValueError("secret file path must be absolute")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("secret file must be regular")
            if stat.S_IMODE(info.st_mode) not in {0o400, 0o600}:
                raise ValueError("secret file permissions must be 0400 or 0600")
            if info.st_uid != os.geteuid():
                raise ValueError("secret file must be owned by the runtime user")
            data = stream.read(MAX_SECRET_BYTES + 1)
        if len(data) > MAX_SECRET_BYTES:
            raise ValueError("secret file exceeds size limit")
        value = data.decode("utf-8").strip()
    except (OSError, UnicodeError):
        raise ValueError(f"cannot read configured secret file for {name}") from None
    if not value:
        raise ValueError(f"configured secret file for {name} is empty")
    if "\x00" in value:
        raise ValueError(f"configured secret file for {name} contains invalid text")
    return value


def environment_secret(name: str, default: str = "") -> str:
    """A configured file is authoritative; conflicting inline values fail closed."""
    path = os.getenv(f"{name}_FILE", "").strip()
    inline = os.getenv(name, "")
    if path:
        if inline:
            raise ValueError(f"configure only one source for {name}")
        return read_secret_file(path, name)
    return os.getenv(name, default)


def apply_secret_files(settings, fields: tuple[str, ...]) -> None:
    """Resolve declared file fields before business configuration validation."""
    for name in fields:
        path = getattr(settings, f"{name}_file", "")
        if path:
            if name in settings.model_fields_set and getattr(settings, name) not in (None, ""):
                raise ValueError(f"configure only one source for {name.upper()}")
            value = read_secret_file(path, name.upper())
            object.__setattr__(settings, name, value)
