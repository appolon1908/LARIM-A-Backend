import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from larimia.finance.models import (
    FinancialAdjustmentRequest,
    PayoutAccount,
    PayoutBatch,
    PayoutItem,
    ProviderPayable,
    ReconciliationBreak,
    ReconciliationRun,
)
from larimia.finance.services import (
    FinancialInvariantError,
    approve_adjustment,
)
from larimia.ledger.infrastructure_models import (
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from larimia.shared.auth import Principal, Role, require_roles
from larimia.shared.db import get_db
from larimia.shared.events import emit
from larimia.shared.idempotency import require_idempotency_key
from larimia.shared.idempotency_service import complete, reserve


router = APIRouter()


class LedgerAdjustmentCreate(BaseModel):
    debit_account: str = Field(min_length=1, max_length=120)
    credit_account: str = Field(min_length=1, max_length=120)
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reason: str = Field(min_length=10, max_length=2_000)


class AdjustmentReject(BaseModel):
    reason: str = Field(min_length=5, max_length=1_000)


class ReconciliationCreate(BaseModel):
    provider_code: str = Field(min_length=1, max_length=80)
    period_start: datetime
    period_end: datetime
    source_reference: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("Reconciliation period must be timezone-aware")
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        if self.period_end - self.period_start > timedelta(days=366):
            raise ValueError("Reconciliation period cannot exceed 366 days")
        return self


class ReconciliationResolution(BaseModel):
    status: str = Field(pattern=r"^(RESOLVED|IGNORED)$")
    resolution: str = Field(min_length=5, max_length=2_000)


class PayoutBatchCreate(BaseModel):
    provider_code: str = Field(min_length=1, max_length=48)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    payable_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def _serialize_adjustment(row: FinancialAdjustmentRequest) -> dict:
    return {
        "id": str(row.id),
        "requested_by": row.requested_by_subject,
        "approved_by": row.approved_by_subject,
        "rejected_by": row.rejected_by_subject,
        "status": row.status,
        "debit_account_id": str(row.debit_account_id),
        "credit_account_id": str(row.credit_account_id),
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "reason": row.reason,
        "version": row.version,
        "ledger_transaction_id": (
            str(row.ledger_transaction_id)
            if row.ledger_transaction_id
            else None
        ),
        "created_at": row.created_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def _serialize_break(row: ReconciliationBreak) -> dict:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id) if row.run_id else None,
        "provider_code": row.provider_code,
        "external_reference": row.external_reference,
        "break_type": row.break_type,
        "status": row.status,
        "currency": row.currency,
        "expected_minor": row.expected_minor,
        "actual_minor": row.actual_minor,
        "details": row.details,
        "resolution": row.resolution,
        "resolved_by": row.resolved_by_subject,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


@router.get("/ledger-accounts")
def ledger_accounts(
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(LedgerAccount)
            .where(LedgerAccount.active.is_(True))
            .order_by(LedgerAccount.currency, LedgerAccount.code)
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "code": row.code,
                "account_type": row.account_type,
                "currency": row.currency,
                "active": row.active,
            }
            for row in rows
        ]
    }


@router.get("/ledger-transactions")
def ledger_transactions(
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(LedgerTransaction)
            .order_by(LedgerTransaction.posted_at.desc())
            .limit(500)
        )
    )
    items = []
    for row in rows:
        entries = list(
            db.scalars(
                select(LedgerEntry)
                .where(LedgerEntry.transaction_id == row.id)
                .order_by(LedgerEntry.id)
            )
        )
        items.append(
            {
                "id": str(row.id),
                "reference_type": row.reference_type,
                "reference_id": row.reference_id,
                "description": row.description,
                "status": row.status,
                "metadata": row.metadata_json,
                "posted_at": row.posted_at.isoformat(),
                "entries": [
                    {
                        "account_id": str(entry.account_id),
                        "direction": entry.direction,
                        "amount_minor": entry.amount_minor,
                        "currency": entry.currency,
                    }
                    for entry in entries
                ],
            }
        )
    return {"items": items}


@router.get("/ledger-adjustments")
def ledger_adjustments(
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(FinancialAdjustmentRequest)
            .order_by(FinancialAdjustmentRequest.created_at.desc())
            .limit(500)
        )
    )
    return {"items": [_serialize_adjustment(row) for row in rows]}


@router.post("/ledger-adjustments", status_code=201)
def create_adjustment(
    payload: LedgerAdjustmentCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    if payload.debit_account == payload.credit_account:
        raise HTTPException(
            422, detail={"code": "ADJUSTMENT_ACCOUNTS_MUST_DIFFER"}
        )
    debit = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.code == payload.debit_account,
            LedgerAccount.active.is_(True),
        )
    )
    credit = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.code == payload.credit_account,
            LedgerAccount.active.is_(True),
        )
    )
    if debit is None or credit is None:
        raise HTTPException(
            422, detail={"code": "LEDGER_ACCOUNT_NOT_FOUND"}
        )
    if debit.currency != payload.currency or credit.currency != payload.currency:
        raise HTTPException(
            422, detail={"code": "LEDGER_ACCOUNT_CURRENCY_MISMATCH"}
        )

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.adjustment.create",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    now = datetime.now(UTC)
    row = FinancialAdjustmentRequest(
        requested_by_subject=principal.subject,
        approved_by_subject=None,
        rejected_by_subject=None,
        status="PENDING_SECOND_APPROVAL",
        debit_account_id=debit.id,
        credit_account_id=credit.id,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        reason=payload.reason,
        version=1,
        ledger_transaction_id=None,
        created_at=now,
        updated_at=now,
        decided_at=None,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        aggregate_type="financial_adjustment",
        aggregate_id=str(row.id),
        event_type="finance.adjustment_requested.v1",
        payload={
            "adjustment_id": str(row.id),
            "requested_by": principal.subject,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
        },
    )
    result = _serialize_adjustment(row)
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/ledger-adjustments/{adjustment_id}/approve")
def approve_ledger_adjustment(
    adjustment_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(FinancialAdjustmentRequest)
        .where(FinancialAdjustmentRequest.id == adjustment_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(
            404, detail={"code": "LEDGER_ADJUSTMENT_NOT_FOUND"}
        )
    if row.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.adjustment.approve",
        key=key,
        payload={"adjustment_id": str(row.id), "version": if_match},
    )
    if replay is not None:
        return replay
    try:
        approve_adjustment(
            db, row, approver_subject=principal.subject
        )
    except FinancialInvariantError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "ADJUSTMENT_APPROVAL_REJECTED",
                "message": str(exc),
            },
        ) from exc
    result = _serialize_adjustment(row)
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/ledger-adjustments/{adjustment_id}/reject")
def reject_ledger_adjustment(
    adjustment_id: uuid.UUID,
    payload: AdjustmentReject,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(FinancialAdjustmentRequest)
        .where(FinancialAdjustmentRequest.id == adjustment_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(
            404, detail={"code": "LEDGER_ADJUSTMENT_NOT_FOUND"}
        )
    if row.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    if row.status != "PENDING_SECOND_APPROVAL":
        raise HTTPException(
            409, detail={"code": "ADJUSTMENT_NOT_PENDING"}
        )
    if row.requested_by_subject == principal.subject:
        raise HTTPException(
            409, detail={"code": "FOUR_EYES_APPROVAL_REQUIRED"}
        )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.adjustment.reject",
        key=key,
        payload={
            "adjustment_id": str(row.id),
            "version": if_match,
            "reason": payload.reason,
        },
    )
    if replay is not None:
        return replay
    now = datetime.now(UTC)
    row.status = "REJECTED"
    row.rejected_by_subject = principal.subject
    row.reason = f"{row.reason}\n\nRejection: {payload.reason}"
    row.decided_at = now
    row.updated_at = now
    row.version += 1
    emit(
        db,
        aggregate_type="financial_adjustment",
        aggregate_id=str(row.id),
        event_type="finance.adjustment_rejected.v1",
        payload={
            "adjustment_id": str(row.id),
            "rejected_by": principal.subject,
        },
    )
    result = _serialize_adjustment(row)
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/reconciliation-runs")
def reconciliation_runs(
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(ReconciliationRun)
            .order_by(ReconciliationRun.created_at.desc())
            .limit(500)
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "provider_code": row.provider_code,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "status": row.status,
                "source_reference": row.source_reference,
                "records_scanned": row.records_scanned,
                "records_matched": row.records_matched,
                "break_count": row.break_count,
                "error_code": row.error_code,
                "created_at": row.created_at.isoformat(),
                "completed_at": (
                    row.completed_at.isoformat()
                    if row.completed_at
                    else None
                ),
            }
            for row in rows
        ]
    }


@router.post("/reconciliation-runs", status_code=202)
def request_reconciliation(
    payload: ReconciliationCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.reconciliation.request",
        key=key,
        payload=payload.model_dump(),
    )
    if replay is not None:
        return replay
    row = ReconciliationRun(
        provider_code=payload.provider_code.lower(),
        period_start=payload.period_start,
        period_end=payload.period_end,
        status="REQUESTED",
        requested_by_subject=principal.subject,
        source_reference=payload.source_reference,
        records_scanned=0,
        records_matched=0,
        break_count=0,
        error_code=None,
        error_message=None,
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
    )
    db.add(row)
    db.flush()
    emit(
        db,
        aggregate_type="reconciliation_run",
        aggregate_id=str(row.id),
        event_type="finance.reconciliation_requested.v1",
        payload={
            "run_id": str(row.id),
            "provider_code": row.provider_code,
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
            "source_reference": row.source_reference,
        },
    )
    result = {"id": str(row.id), "status": row.status}
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/reconciliation-breaks")
def reconciliation_breaks(
    status: str | None = Query(
        default=None, pattern=r"^(OPEN|RESOLVED|IGNORED)$"
    ),
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    statement = select(ReconciliationBreak)
    if status:
        statement = statement.where(ReconciliationBreak.status == status)
    rows = list(
        db.scalars(
            statement.order_by(ReconciliationBreak.created_at.desc()).limit(500)
        )
    )
    return {"items": [_serialize_break(row) for row in rows]}


@router.post("/reconciliation-breaks/{break_id}/resolve")
def resolve_reconciliation_break(
    break_id: uuid.UUID,
    payload: ReconciliationResolution,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(ReconciliationBreak)
        .where(ReconciliationBreak.id == break_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(
            404, detail={"code": "RECONCILIATION_BREAK_NOT_FOUND"}
        )
    if row.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    if row.status != "OPEN":
        raise HTTPException(
            409, detail={"code": "RECONCILIATION_BREAK_CLOSED"}
        )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.reconciliation_break.resolve",
        key=key,
        payload={"break_id": str(row.id), "version": if_match, **payload.model_dump()},
    )
    if replay is not None:
        return replay
    row.status = payload.status
    row.resolution = payload.resolution
    row.resolved_by_subject = principal.subject
    row.resolved_at = datetime.now(UTC)
    row.version += 1
    emit(
        db,
        aggregate_type="reconciliation_break",
        aggregate_id=str(row.id),
        event_type="finance.reconciliation_break_resolved.v1",
        payload={
            "break_id": str(row.id),
            "status": row.status,
            "resolved_by": principal.subject,
        },
    )
    result = _serialize_break(row)
    complete(db, idem, result)
    db.commit()
    return result


@router.get("/provider-payables")
def provider_payables(
    status: str | None = Query(default=None),
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    statement = select(ProviderPayable)
    if status:
        statement = statement.where(ProviderPayable.status == status)
    rows = list(
        db.scalars(
            statement.order_by(ProviderPayable.created_at.desc()).limit(1_000)
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "provider_id": str(row.provider_id),
                "booking_id": str(row.booking_id),
                "payment_intent_id": str(row.payment_intent_id),
                "currency": row.currency,
                "service_subtotal_minor": row.service_subtotal_minor,
                "platform_fee_minor": row.platform_fee_minor,
                "adjustment_minor": row.adjustment_minor,
                "net_minor": row.net_minor,
                "status": row.status,
                "available_at": row.available_at.isoformat(),
                "hold_reason": row.hold_reason,
            }
            for row in rows
        ]
    }


@router.get("/payout-batches")
def payout_batches(
    _: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    rows = list(
        db.scalars(
            select(PayoutBatch)
            .order_by(PayoutBatch.created_at.desc())
            .limit(500)
        )
    )
    return {
        "items": [
            {
                "id": str(row.id),
                "batch_number": row.batch_number,
                "provider_code": row.provider_code,
                "currency": row.currency,
                "status": row.status,
                "total_minor": row.total_minor,
                "item_count": row.item_count,
                "requested_by": row.requested_by_subject,
                "approved_by": row.approved_by_subject,
                "version": row.version,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/payout-batches", status_code=201)
def create_payout_batch(
    payload: PayoutBatchCreate,
    key: str = Depends(require_idempotency_key),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    unique_ids = list(dict.fromkeys(payload.payable_ids))
    if len(unique_ids) != len(payload.payable_ids):
        raise HTTPException(
            422, detail={"code": "DUPLICATE_PAYABLE_ID"}
        )
    payables = list(
        db.scalars(
            select(ProviderPayable)
            .where(ProviderPayable.id.in_(unique_ids))
            .with_for_update()
        )
    )
    if len(payables) != len(unique_ids):
        raise HTTPException(
            404, detail={"code": "PROVIDER_PAYABLE_NOT_FOUND"}
        )
    for payable in payables:
        if payable.status != "AVAILABLE":
            raise HTTPException(
                409,
                detail={
                    "code": "PROVIDER_PAYABLE_NOT_AVAILABLE",
                    "payable_id": str(payable.id),
                },
            )
        if payable.currency != payload.currency:
            raise HTTPException(
                422, detail={"code": "PAYOUT_CURRENCY_MISMATCH"}
            )

    account_by_provider: dict[uuid.UUID, PayoutAccount] = {}
    for payable in payables:
        account = db.scalar(
            select(PayoutAccount).where(
                PayoutAccount.provider_id == payable.provider_id,
                PayoutAccount.provider_code == payload.provider_code,
                PayoutAccount.currency == payload.currency,
                PayoutAccount.status == "VERIFIED",
                PayoutAccount.active.is_(True),
            )
        )
        if account is None:
            raise HTTPException(
                409,
                detail={
                    "code": "VERIFIED_PAYOUT_ACCOUNT_REQUIRED",
                    "provider_id": str(payable.provider_id),
                },
            )
        account_by_provider[payable.provider_id] = account

    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.payout_batch.create",
        key=key,
        payload={
            "provider_code": payload.provider_code,
            "currency": payload.currency,
            "payable_ids": sorted(str(value) for value in unique_ids),
        },
    )
    if replay is not None:
        return replay

    now = datetime.now(UTC)
    total = sum(row.net_minor + row.adjustment_minor for row in payables)
    if total <= 0:
        raise HTTPException(
            409, detail={"code": "PAYOUT_BATCH_TOTAL_INVALID"}
        )
    batch = PayoutBatch(
        batch_number=f"PO-{now:%Y%m%d}-{secrets.token_hex(4).upper()}",
        provider_code=payload.provider_code,
        currency=payload.currency,
        status="PENDING_APPROVAL",
        total_minor=total,
        item_count=len(payables),
        requested_by_subject=principal.subject,
        approved_by_subject=None,
        version=1,
        created_at=now,
        approved_at=None,
        completed_at=None,
    )
    db.add(batch)
    db.flush()
    for payable in payables:
        amount = payable.net_minor + payable.adjustment_minor
        payable.status = "RESERVED"
        payable.updated_at = now
        db.add(
            PayoutItem(
                batch_id=batch.id,
                payable_id=payable.id,
                provider_id=payable.provider_id,
                payout_account_id=account_by_provider[payable.provider_id].id,
                amount_minor=amount,
                currency=payload.currency,
                status="PENDING",
                external_payout_id=None,
                error_code=None,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
        )
    emit(
        db,
        aggregate_type="payout_batch",
        aggregate_id=str(batch.id),
        event_type="payout.batch_created.v1",
        payload={
            "batch_id": str(batch.id),
            "batch_number": batch.batch_number,
            "total_minor": batch.total_minor,
            "currency": batch.currency,
            "item_count": batch.item_count,
        },
    )
    result = {
        "id": str(batch.id),
        "batch_number": batch.batch_number,
        "status": batch.status,
        "total_minor": batch.total_minor,
        "currency": batch.currency,
        "item_count": batch.item_count,
        "version": batch.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/payout-batches/{batch_id}/approve")
def approve_payout_batch(
    batch_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    batch = db.scalar(
        select(PayoutBatch)
        .where(PayoutBatch.id == batch_id)
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(
            404, detail={"code": "PAYOUT_BATCH_NOT_FOUND"}
        )
    if batch.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    if batch.status != "PENDING_APPROVAL":
        raise HTTPException(
            409, detail={"code": "PAYOUT_BATCH_NOT_PENDING"}
        )
    if batch.requested_by_subject == principal.subject:
        raise HTTPException(
            409, detail={"code": "FOUR_EYES_APPROVAL_REQUIRED"}
        )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.payout_batch.approve",
        key=key,
        payload={"batch_id": str(batch.id), "version": if_match},
    )
    if replay is not None:
        return replay
    batch.status = "APPROVED"
    batch.approved_by_subject = principal.subject
    batch.approved_at = datetime.now(UTC)
    batch.version += 1
    emit(
        db,
        aggregate_type="payout_batch",
        aggregate_id=str(batch.id),
        event_type="payout.batch_approved.v1",
        payload={
            "batch_id": str(batch.id),
            "provider_code": batch.provider_code,
            "approved_by": principal.subject,
            "live_submission_enabled": False,
        },
    )
    result = {
        "id": str(batch.id),
        "status": batch.status,
        "version": batch.version,
    }
    complete(db, idem, result)
    db.commit()
    return result


@router.post("/payout-batches/{batch_id}/cancel")
def cancel_payout_batch(
    batch_id: uuid.UUID,
    key: str = Depends(require_idempotency_key),
    if_match: int = Header(alias="If-Match", ge=1),
    principal: Principal = Depends(require_roles(Role.FINANCE)),
    db: Session = Depends(get_db),
):
    batch = db.scalar(
        select(PayoutBatch)
        .where(PayoutBatch.id == batch_id)
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(
            404, detail={"code": "PAYOUT_BATCH_NOT_FOUND"}
        )
    if batch.version != if_match:
        raise HTTPException(409, detail={"code": "VERSION_CONFLICT"})
    if batch.status not in {"PENDING_APPROVAL", "APPROVED"}:
        raise HTTPException(
            409, detail={"code": "PAYOUT_BATCH_NOT_CANCELLABLE"}
        )
    idem, replay = reserve(
        db,
        actor_subject=principal.subject,
        operation="finance.payout_batch.cancel",
        key=key,
        payload={"batch_id": str(batch.id), "version": if_match},
    )
    if replay is not None:
        return replay
    items = list(
        db.scalars(
            select(PayoutItem)
            .where(PayoutItem.batch_id == batch.id)
            .with_for_update()
        )
    )
    now = datetime.now(UTC)
    for item in items:
        payable = db.get(ProviderPayable, item.payable_id, with_for_update=True)
        if payable is not None and payable.status == "RESERVED":
            payable.status = "AVAILABLE"
            payable.updated_at = now
        item.status = "CANCELLED"
        item.updated_at = now
    batch.status = "CANCELLED"
    batch.version += 1
    emit(
        db,
        aggregate_type="payout_batch",
        aggregate_id=str(batch.id),
        event_type="payout.batch_cancelled.v1",
        payload={"batch_id": str(batch.id), "actor": principal.subject},
    )
    result = {
        "id": str(batch.id),
        "status": batch.status,
        "version": batch.version,
    }
    complete(db, idem, result)
    db.commit()
    return result
