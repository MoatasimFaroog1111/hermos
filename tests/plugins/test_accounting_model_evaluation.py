from __future__ import annotations

import base64
import json
from datetime import date, timedelta
from pathlib import Path

from plugins.accounting_brain.model_evaluation.prepare import (
    prepare_evaluation_evidence,
)
from plugins.accounting_brain.model_evaluation.scoring import (
    aggregate_evaluation_scores,
    score_journal_prediction,
)


class FakeReader:
    def fields_get(self, model: str, *, attributes=None):
        assert model == "ir.attachment"
        return {"datas": {"type": "binary"}}

    def read(self, model: str, ids, *, fields=None):
        assert model == "ir.attachment"
        payload = base64.b64encode(b"%PDF-1.4 test accounting evidence").decode()
        return [{"id": int(identifier), "datas": payload} for identifier in ids]


def _pair(index: int, *, status: str = "metadata_only", checksum: str | None = None):
    event_date = date(2025, 1, 1) + timedelta(days=index)
    attachment_id = 1000 + index
    attachment = {
        "attachment_id": attachment_id,
        "filename": f"invoice-{index}.pdf",
        "mimetype": "application/pdf",
        "file_size": 1024,
        "checksum": checksum or f"checksum-{index}",
        "local_path": None,
        "content_sha256": None,
        "content_status": status,
    }
    return {
        "source_move_id": index,
        "source_move_name": f"INV/{index}",
        "grade": "gold",
        "quality_reasons": [],
        "input": {
            "contract_version": "1.0",
            "source_system": "odoo",
            "document": {
                "move_type": "in_invoice",
                "reference": f"VENDOR-{index}",
                "date": event_date.isoformat(),
                "invoice_date": event_date.isoformat(),
                "partner": {"id": 44, "name": "Vendor"},
                "journal": {"id": 9, "name": "Vendor Bills"},
                "company": {"id": 1, "name": "GITC"},
                "currency": {"id": 1, "name": "SAR"},
                "amount_untaxed": "100.00",
                "amount_tax": "15.00",
                "amount_total": "115.00",
            },
            "attachments": [attachment],
        },
        "target": _target(),
    }


def _target():
    return {
        "move_type": "in_invoice",
        "partner": {"id": 44, "name": "Vendor"},
        "journal": {"id": 9, "name": "Vendor Bills"},
        "company": {"id": 1, "name": "GITC"},
        "currency": {"id": 1, "name": "SAR"},
        "taxes": [{"id": 3, "name": "VAT 15%"}],
        "journal_entry": [
            {
                "account_id": 501,
                "account_code": "500100",
                "debit": "100.00",
                "credit": "0.00",
                "tax_ids": [3],
                "analytic_distribution": None,
            },
            {
                "account_id": 202,
                "account_code": "202000",
                "debit": "15.00",
                "credit": "0.00",
                "tax_ids": [],
                "analytic_distribution": None,
            },
            {
                "account_id": 401,
                "account_code": "401000",
                "debit": "0.00",
                "credit": "115.00",
                "tax_ids": [],
                "analytic_distribution": None,
            },
        ],
    }


def _write_dataset(root: Path, count: int = 30) -> Path:
    dataset = root / "golden-20260903T000000000000Z"
    dataset.mkdir(parents=True)
    with (dataset / "pairs.jsonl").open("w", encoding="utf-8") as handle:
        for index in range(1, count + 1):
            handle.write(json.dumps(_pair(index), sort_keys=True) + "\n")
    return dataset


def test_evaluation_gate_blocks_metadata_only_source_evidence(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)

    result = prepare_evaluation_evidence(
        FakeReader(),
        tmp_path,
        min_holdout=5,
        holdout_fraction=0.20,
        min_source_content_coverage=0.90,
    )

    assert result["ok"] is False
    assert result["stage"] == "BLOCKED_BY_SOURCE_EVIDENCE"
    assert result["next_action"] == "HYDRATE_SAFE_GOLD_ATTACHMENTS"
    assert result["holdout_cases"] == 6
    assert result["gates"]["source_content_coverage"]["value"] == 0.0
    assert result["gates"]["model_training_enabled"] is False
    assert result["safety"]["odoo_mutations"] is False

    inputs = [
        json.loads(line)
        for line in (dataset / "evaluation" / "evaluation-inputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert inputs
    serialized = json.dumps(inputs[0], sort_keys=True)
    assert "target" not in inputs[0]
    assert "journal" not in serialized
    assert "partner" not in serialized
    assert "source_move_id" not in serialized


def test_evaluation_gate_hydrates_safe_gold_content_read_only(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)

    result = prepare_evaluation_evidence(
        FakeReader(),
        tmp_path,
        hydrate_source_content=True,
        max_attachment_bytes=2 * 1024 * 1024,
        min_holdout=5,
        holdout_fraction=0.20,
        min_source_content_coverage=0.90,
    )

    assert result["ok"] is True
    assert result["stage"] == "EVALUATION_DATA_READY"
    assert result["next_action"] == "RUN_BASELINE_MODEL_EVALUATION"
    assert result["gates"]["source_content_coverage"]["value"] == 1.0
    assert result["hydration"]["attachment_status_counts"]["downloaded"] == 30
    assert result["safety"] == {
        "odoo_mutations": False,
        "training_performed": False,
        "auto_post": False,
        "secrets_exposed": False,
    }
    assert (dataset / "source-hydration-report.json").is_file()
    assert any((dataset / "attachments").iterdir())


def test_exact_attachment_duplicate_is_removed_from_holdout(tmp_path: Path) -> None:
    dataset = tmp_path / "golden-20260903T000000000000Z"
    dataset.mkdir(parents=True)
    rows = [_pair(index) for index in range(1, 31)]
    rows[-1]["input"]["attachments"][0]["checksum"] = rows[0]["input"]["attachments"][0]["checksum"]
    with (dataset / "pairs.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    result = prepare_evaluation_evidence(
        FakeReader(),
        tmp_path,
        min_holdout=5,
        holdout_fraction=0.20,
    )

    assert result["duplicate_checksum_exclusions"] == 1
    assert result["holdout_cases"] == 5


def test_deterministic_scorer_requires_exact_accounting_target() -> None:
    expected = _target()
    exact = score_journal_prediction(expected, expected)
    assert exact["pass"] is True
    assert exact["critical"]["balanced"] is True
    assert exact["critical"]["account_amount_exact"] is True

    wrong = json.loads(json.dumps(expected))
    wrong["journal_entry"][0]["account_code"] = "999999"
    score = score_journal_prediction(expected, wrong)
    assert score["pass"] is False
    assert score["critical"]["balanced"] is True
    assert score["critical"]["account_amount_exact"] is False

    aggregate = aggregate_evaluation_scores([exact, score])
    assert aggregate["cases"] == 2
    assert aggregate["strict_pass_rate"] == 0.5
