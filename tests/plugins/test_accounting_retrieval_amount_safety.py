from plugins.accounting_brain.model_evaluation.retrieval import _compact_target


def test_amount_free_historical_projection_preserves_direction_and_ids() -> None:
    target = {
        "move_type": "in_invoice",
        "journal": {"id": 3, "name": "Vendor Bills"},
        "currency": {"id": 1, "name": "SAR"},
        "journal_entry": [
            {
                "account_id": 501,
                "account_code": "410004",
                "account_name": "Consumable Materials",
                "debit": "123.45",
                "credit": "0.00",
                "tax_ids": [14],
                "analytic_distribution": {"7": 100.0},
            },
            {
                "account_id": 201,
                "account_code": "201002",
                "account_name": "Payables",
                "debit": "0.00",
                "credit": "123.45",
                "tax_ids": [],
                "analytic_distribution": {},
            },
        ],
    }

    projected = _compact_target(target, include_amounts=False)
    lines = projected["journal_entry"]

    assert projected["journal"] == {"id": 3, "name": "Vendor Bills"}
    assert projected["currency"] == {"id": 1, "name": "SAR"}
    assert lines[0]["account_id"] == 501
    assert lines[0]["direction"] == "debit"
    assert lines[1]["direction"] == "credit"
    assert "debit" not in lines[0]
    assert "credit" not in lines[0]
    assert "debit" not in lines[1]
    assert "credit" not in lines[1]
    assert "123.45" not in str(projected)


def test_default_historical_projection_retains_amounts_for_legacy_callers() -> None:
    target = {
        "journal_entry": [
            {
                "account_id": 501,
                "account_code": "410004",
                "debit": "123.45",
                "credit": "0.00",
            }
        ]
    }

    projected = _compact_target(target)

    assert projected["journal_entry"][0]["debit"] == "123.45"
    assert projected["journal_entry"][0]["credit"] == "0.00"
