import uuid
from datetime import datetime
from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from larimia.shared.db import Base

class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    account_type: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str] = mapped_column(String(3))

class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_type: Mapped[str] = mapped_column(String(80))
    reference_id: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    direction: Mapped[str] = mapped_column(String(6))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
