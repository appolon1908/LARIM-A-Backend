import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from larimia.finance.models import FinancialAdjustmentRequest
from larimia.finance.services import (
    FinancialInvariantError,
    JournalLine,
    approve_adjustment,
    post_journal,
)
from larimia.ledger.infrastructure_models import (
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from larimia.shared.db import SessionLocal


def _accounts(db):
    debit = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.code == "PROCESSOR_CLEARING:DOP"
        )
    )
    credit = db.scalar(
        select(LedgerAccount).where(
            LedgerAccount.code == "PROVIDER_PAYABLE:DOP"
        )
    )
    assert debit is not None
    assert credit is not None
    return debit, credit


def test_balanced_journal_is_idempotent():
    with SessionLocal() as db:
        reference_id = str(uuid.uuid4())
        first = post_journal(
            db,
            reference_type="TEST",
            reference_id=reference_id,
            description="balanced test journal",
            lines=[
                JournalLine(
                    "PROCESSOR_CLEARING:DOP",
                    "DEBIT",
                    10_000,
                    "DOP",
                ),
                JournalLine(
                    "PROVIDER_PAYABLE:DOP",
                    "CREDIT",
                    10_000,
                    "DOP",
                ),
            ],
        )
        second = post_journal(
            db,
            reference_type="TEST",
            reference_id=reference_id,
            description="replayed test journal",
            lines=[
                JournalLine(
                    "PROCESSOR_CLEARING:DOP",
                    "DEBIT",
                    10_000,
                    "DOP",
                ),
                JournalLine(
                    "PROVIDER_PAYABLE:DOP",
                    "CREDIT",
                    10_000,
                    "DOP",
                ),
            ],
        )
        assert first.id == second.id
        assert db.scalar(
            select(func.count(LedgerTransaction.id)).where(
                LedgerTransaction.reference_type == "TEST",
                LedgerTransaction.reference_id == reference_id,
            )
        ) == 1
        assert db.scalar(
            select(func.count(LedgerEntry.id)).where(
                LedgerEntry.transaction_id == first.id
            )
        ) == 2
        db.rollback()


def test_unbalanced_journal_is_rejected():
    with SessionLocal() as db:
        with pytest.raises(FinancialInvariantError):
            post_journal(
                db,
                reference_type="TEST",
                reference_id=str(uuid.uuid4()),
                description="unbalanced",
                lines=[
                    JournalLine(
                        "PROCESSOR_CLEARING:DOP",
                        "DEBIT",
                        10_000,
                        "DOP",
                    ),
                    JournalLine(
                        "PROVIDER_PAYABLE:DOP",
                        "CREDIT",
                        9_999,
                        "DOP",
                    ),
                ],
            )
        db.rollback()


def test_adjustment_requires_independent_approver():
    with SessionLocal() as db:
        debit, credit = _accounts(db)
        now = datetime.now(UTC)
        request = FinancialAdjustmentRequest(
            requested_by_subject="finance-requester",
            approved_by_subject=None,
            rejected_by_subject=None,
            status="PENDING_SECOND_APPROVAL",
            debit_account_id=debit.id,
            credit_account_id=credit.id,
            amount_minor=5_000,
            currency="DOP",
            reason="Correct an independently reviewed settlement variance",
            version=1,
            ledger_transaction_id=None,
            created_at=now,
            updated_at=now,
            decided_at=None,
        )
        db.add(request)
        db.flush()
        with pytest.raises(FinancialInvariantError):
            approve_adjustment(
                db,
                request,
                approver_subject="finance-requester",
            )

        transaction = approve_adjustment(
            db,
            request,
            approver_subject="finance-approver",
        )
        assert request.status == "POSTED"
        assert request.approved_by_subject == "finance-approver"
        assert request.ledger_transaction_id == transaction.id
        assert request.version == 2
        db.rollback()
