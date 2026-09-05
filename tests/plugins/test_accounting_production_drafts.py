from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from plugins.accounting_brain.production_drafts.predict import (
    prepare_accounting_draft,
)
from plugins.accounting_brain.production_drafts.validation import (
    validate_draft_prediction,
)


def _prediction() -> dict:
    return {
        "move_type": "in_invoice",
        "date": "2026-09-05",
        "reference": "INV-100",
        "journal": {"id": 3, "name": "Vendor Bills"},
        "partner": {"id": 9, "name": "Supplier"},
        "company": {"id": 1, "name": "Guardian"},
        "currency": {"id": 1, "name": "SAR"},
        "taxes": [],
        "journal_entry": [
            {
                "account_code": "510100",
                "debit": "100.00",
                "credit": "0.00",
                "tax_ids": [],
                "analytic_distribution": {},
            },
            {
                "account_code": "211000",
                "debit": "0.00",
                "credit": "100.00",
                "tax_ids": [],
                "analytic_distribution": {},
            },
        ],
    }


class FakeLlm:
    def complete_structured(self, **kwargs):
        return SimpleNamespace(
            parsed=_prediction(),
            provider="fake",
            model="fake-accountant",
        )


def test_draft_validator_accepts_balanced_structured_entry() -> None:
    result = validate_draft_prediction(_prediction())

    assert result["valid"] is True
    assert result["balanced"] is True
    assert result["auto_post_allowed"] is False
    assert result["human_review_required"] is True


def test_draft_validator_rejects_unbalanced_entry() -> None:
    prediction = _prediction()
    prediction["journal_entry"][1]["credit"] = "99.00"

    result = validate_draft_prediction(prediction)

    assert result["valid"] is False
    assert "journal entry is not balanced" in result["errors"]


def test_draft_validator_requires_company_and_date() -> None:
    prediction = _prediction()
    prediction.pop("company")
    prediction["date"] = "not-a-date"

    result = validate_draft_prediction(prediction)

    assert result["valid"] is False
    assert "company requires a positive Odoo id" in result["errors"]
    assert "date must be a valid YYYY-MM-DD accounting date" in result["errors"]


def test_production_predictor_persists_review_only_proposal(tmp_path: Path) -> None:
    home = tmp_path / "home"
    dataset = home / "accounting_brain" / "datasets" / "golden-1"
    attachments = dataset / "attachments"
    attachments.mkdir(parents=True)
    historical = attachments / "office.txt"
    historical.write_text("office supplies paper toner SAR 100", encoding="utf-8")
    source = home / "inbox" / "new-office.txt"
    source.parent.mkdir(parents=True)
    source.write_text("office supplies paper toner SAR 100", encoding="utf-8")

    pair = {
        "grade": "gold",
        "source_move_id": 1,
        "input": {
            "document": {"date": "2026-01-01"},
            "attachments": [
                {
                    "filename": "office.txt",
                    "mimetype": "text/plain",
                    "local_path": "attachments/office.txt",
                    "content_status": "downloaded",
                }
            ],
        },
        "target": _prediction(),
    }
    (dataset / "pairs.jsonl").write_text(
        json.dumps(pair) + "\n",
        encoding="utf-8",
    )

    result = prepare_accounting_draft(
        source,
        hermes_home=home,
        datasets_root=home / "accounting_brain" / "datasets",
        output_root=home / "accounting_brain" / "drafts",
        llm=FakeLlm(),
        top_k=1,
    )

    assert result["ok"] is True
    assert result["stage"] == "READY_FOR_HUMAN_REVIEW"
    assert result["production_mode"] == "draft_only"
    assert result["safety"]["odoo_write_performed"] is False
    assert result["safety"]["auto_post"] is False
    assert result["safety"]["human_review_required"] is True
    assert (home / "accounting_brain" / "drafts" / result["proposal_file"]).is_file()
