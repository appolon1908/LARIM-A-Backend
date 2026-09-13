from dataclasses import dataclass

from larimia.shared.auth import Principal


@dataclass(frozen=True)
class CommandContext:
    principal: Principal
    request_id: str
    correlation_id: str
    idempotency_key: str | None
    ip_address: str | None
    user_agent: str | None
