from __future__ import annotations

from plugins.accounting_brain.journal_training.models import TrainingGrade
from plugins.accounting_brain.journal_training.quality import grade_training_example


def _balanced_lines():
    return [
        {"account_id": [10, "Expense"], "debit": 100.0, "credit": 0.0},
        {"account_id": [20, "Payable"], "debit": 0.0, "credit": 100.0},
    ]


def test_posted_balanced_entry_with_attachment_is_gold() -> None:
    decision = grade_training_example(
        {"state": "posted", "move_type": "entry", "auto_post": "no"},
        _balanced_lines(),
        [{"id": 1, "name": "evidence.pdf"}],
    )
    assert decision.grade is TrainingGrade.GOLD
    assert decision.reasons == ()


def test_valid_entry_without_source_attachment_is_silver() -> None:
    decision = grade_training_example(
        {"state": "posted", "move_type": "entry", "auto_post": "no"},
        _balanced_lines(),
        [],
    )
    assert decision.grade is TrainingGrade.SILVER
    assert "no_source_attachment" in decision.reasons


def test_unbalanced_entry_is_rejected() -> None:
    decision = grade_training_example(
        {"state": "posted", "move_type": "entry", "auto_post": "no"},
        [
            {"account_id": [10, "Expense"], "debit": 100.0, "credit": 0.0},
            {"account_id": [20, "Payable"], "debit": 0.0, "credit": 99.0},
        ],
        [{"id": 1, "name": "evidence.pdf"}],
    )
    assert decision.grade is TrainingGrade.REJECTED
    assert decision.reasons == ("journal_not_balanced",)


def test_vendor_bill_without_partner_requires_review() -> None:
    decision = grade_training_example(
        {"state": "posted", "move_type": "in_invoice", "auto_post": "no"},
        _balanced_lines(),
        [{"id": 1, "name": "vendor-bill.pdf"}],
    )
    assert decision.grade is TrainingGrade.SILVER
    assert "partner_missing_for_document_move" in decision.reasons
