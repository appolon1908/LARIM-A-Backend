import uuid
from datetime import datetime
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from larimia.shared.db import Base

class IntegrationStatus(Base):
    __tablename__ = "integration_status"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    readiness: Mapped[str] = mapped_column(String(32), default="UNCONFIGURED", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
