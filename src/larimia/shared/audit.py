import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from larimia.shared.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_subject: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[str] = mapped_column(String(255), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def record_audit(
    db: Session,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_subject=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata or {},
        )
    )
