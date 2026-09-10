"""STEP 6 tests for leakage-safe GITC memory and grounded evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.accounting_brain.model_evaluation import grounded_runner
from plugins.accounting_brain.model_evaluation.company_memory import (
    CompanyMemory,
    build_memory_hints,
    derive_company_memory,
)
from plugins.accounting_brain.model_evaluation.grounded_runner import (
    run_grounded_evaluation,
)
from plugins.accounting_brain.production_drafts.predict import (
    prepare_accounting_draft,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prediction() -> dict:
    return {
        "move_type": "entry",
        "journal": {"id": 7, "code": "MISC", "name": "Miscellaneous"},
        "partner": {"id": 90, "name": "Supplier A"},
        "currency": {"id": 1, "name": "SAR"},
        "taxes": [{"id": 14, "name": "VAT 15%"}],
        "journal_entry": [
            {
                "account_id": 501,
                "account_code": "510000",
                "account_name": "Materials Expense",
                "partner_id": 90,
                "partner_name": "Supplier A",
                "label": "Materials",
                "debit": "100.00",
                "credit": "0.00",
                "tax_ids": [14],
                "analytic_distribution": {"11": 100},
            },
            {
                "account_id": 201,
                "account_code": "211000",
                "account_name": "Accounts Payable",
                "partner_id": 90,
                "partner_name": "Supplier A",
                "label": "Payable",
                "debit": "0.00",
                "credit": "100.00",
                "tax_ids": [],
                "analytic_distribution": {},
            },
        ],
    }


def _invalid_prediction() -> dict:
    value = _prediction()
    value["journal_entry"][0].pop("analytic_distribution")
    return value


def _reference_row() -> dict:
    return {
        "contract_version": "1.0",
        "reference_id": "move-1",
        "source_move_id": 1,
        "source": {
            "attachments": [
                {
                    "filename": "history.txt",
                    "mimetype": "text/plain",
                    "local_path": "attachments/history.txt",
                    "content_status": "downloaded",
                    "checksum": "must-not-enter-memory",
                }
            ]
        },
        "target": _prediction(),
    }


def _prepared_evaluation(tmp_path: Path) -> Path:
    dataset = tmp_path / "golden-20260905T000000Z"
    evaluation = dataset / "evaluation"
    attachments = dataset / "attachments"
    evaluation.mkdir(parents=True)
    attachments.mkdir(parents=True)
    (attachments / "current.txt").write_text(
        "Supplier A materials VAT SAR 100.00",
        encoding="utf-8",
    )
    (attachments / "history.txt").write_text(
        "Supplier A materials VAT SAR historical document",
        encoding="utf-8",
    )

    _write_json(
        evaluation / "evaluation-manifest.json",
        {
            "ok": True,
            "stage": "EVALUATION_DATA_READY",
            "contract_version": "1.0",
            "gates": {
                "gold_only": True,
                "single_company_scope": True,
                "temporal_holdout": {"pass": True},
                "exact_attachment_checksum_leakage_removed": True,
                "model_input_target_leakage_blocked": True,
                "source_content_coverage": {"pass": True},
                "auto_post_disabled": True,
                "human_review_required": True,
            },
        },
    )
    _write_jsonl(
        evaluation / "evaluation-inputs.jsonl",
        [
            {
                "contract_version": "1.0",
                "case_id": "case-1",
                "source": {
                    "attachments": [
                        {
                            "filename": "current.txt",
                            "mimetype": "text/plain",
                            "local_path": "attachments/current.txt",
                            "content_status": "downloaded",
                        }
                    ]
                },
            }
        ],
    )
    _write_jsonl(
        evaluation / "evaluation-reference.jsonl",
        [_reference_row()],
    )
    _write_jsonl(
        evaluation / "evaluation-ground-truth.jsonl",
        [
            {
                "contract_version": "1.0",
                "case_id": "case-1",
                "target": _prediction(),
            }
        ],
    )
    return dataset


class FakeLlm:
    def __init__(self, prediction: dict | None = None) -> None:
        self.prediction = prediction or _prediction()
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed=self.prediction,
            provider="fake",
            model="fake-accountant",
            usage=SimpleNamespace(
                input_tokens=11,
                output_tokens=22,
                total_tokens=33,
                cost_usd=0.01,
            ),
        )


class BadRequestError(Exception):
    pass


class JsonSchemaRejectingLlm(FakeLlm):
    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("json_schema") is not None:
            raise BadRequestError(
                "response_format type json_schema is unsupported; use json_object"
            )
        return SimpleNamespace(
            parsed=self.prediction,
            provider="deepseek",
            model="deepseek-v4-pro",
            usage=SimpleNamespace(
                input_tokens=13,
                output_tokens=17,
                total_tokens=30,
                cost_usd=0.02,
            ),
        )


class RepairingLlm(FakeLlm):
    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        value = (
            _prediction()
            if kwargs.get("purpose") == "accounting_baseline_schema_repair"
            else _invalid_prediction()
        )
        return SimpleNamespace(
            parsed=value,
            provider="deepseek",
            model="deepseek-v4-pro",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                cost_usd=0.01,
            ),
        )


class CapturingDraftLlm:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        prediction = _prediction()
        prediction.update(
            {
                "date": "2026-09-10",
                "reference": "INV-1",
                "company": {"id": 1, "name": "GITC"},
            }
        )
        return SimpleNamespace(
            parsed=prediction,
            provider="fake",
            model="fake-accountant",
        )


def test_company_memory_preserves_exact_odoo_ids_and_no_amounts() -> None:
    memory = derive_company_memory([_reference_row()])
    hints = build_memory_hints(memory)

    assert "id=7" in hints
    assert "id=1" in hints
    assert "id=14" in hints
    assert "code=510000 id=501" in hints
    assert "debit-prior=1.00" in hints
    assert "credit-prior=1.00" in hints
    assert "100.00" not in hints
    assert "must-not-enter-memory" not in hints
    assert "source_move_id" not in json.dumps(memory.to_dict())


def test_company_memory_tracks_journal_move_type_and_analytics() -> None:
    memory = derive_company_memory([_reference_row()])

    assert memory.journal_move_type_pairs[("id:7", "entry")] == 1
    assert memory.move_type_journal_pairs[("entry", "id:7")] == 1
    assert memory.account_debit_count["510000"] == 1
    assert memory.account_credit_count["211000"] == 1
    assert memory.analytic_patterns['{"11":100}'] == 1


def test_company_memory_roundtrip_is_json_safe() -> None:
    memory = derive_company_memory([_reference_row()])
    payload = json.loads(json.dumps(memory.to_dict()))
    restored = CompanyMemory.from_dict(payload)

    assert restored.journal_move_type_pairs == memory.journal_move_type_pairs
    assert restored.account_catalog == memory.account_catalog
    assert restored.currency_catalog == memory.currency_catalog


def test_grounded_runner_routes_fixed_predictions_through_trusted_production_gate(
    tmp_path: Path,
) -> None:
    dataset = _prepared_evaluation(tmp_path)
    result = run_grounded_evaluation(tmp_path, FakeLlm())

    assert result["stage"] == result["score_report"]["stage"]
    assert result["production_gate"] == result["score_report"]["production_gate"]
    assert result["score_report"]["evaluation_cases"] == 1
    assert result["safety"]["predictions_fixed_before_scoring"] is True
    assert (dataset / "evaluation" / "evaluation-predictions.jsonl").is_file()
    assert not (dataset / "evaluation" / "evaluation-grounded-predictions.jsonl").exists()


def test_grounded_inference_loader_never_reads_ground_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepared_evaluation(tmp_path)
    original = grounded_runner._load_jsonl

    def guarded(path: Path):
        assert path.name != "evaluation-ground-truth.jsonl"
        return original(path)

    monkeypatch.setattr(grounded_runner, "_load_jsonl", guarded)
    result = run_grounded_evaluation(tmp_path, FakeLlm())

    assert result["score_report"]["evaluation_cases"] == 1


def test_grounded_runner_includes_memory_and_retrieval_without_current_truth(
    tmp_path: Path,
) -> None:
    _prepared_evaluation(tmp_path)
    llm = FakeLlm()

    run_grounded_evaluation(tmp_path, llm, top_k=1)

    serialized = json.dumps(llm.calls[0], default=str)
    assert "GITC ACCOUNTING MEMORY" in serialized
    assert "RETRIEVED EARLIER GOLD EXAMPLES" in serialized
    assert "id=7" in serialized
    assert "evaluation-ground-truth" not in serialized


def test_grounded_runner_uses_exact_deepseek_json_fallback(tmp_path: Path) -> None:
    _prepared_evaluation(tmp_path)
    llm = JsonSchemaRejectingLlm()

    result = run_grounded_evaluation(tmp_path, llm)

    assert result["json_schema_fallbacks"] == 1
    assert len(llm.calls) == 2
    assert llm.calls[0]["json_schema"] is not None
    assert llm.calls[1]["json_schema"] is None
    assert "JSON schema" in llm.calls[1]["instructions"]
    assert result["usage"] == {
        "input_tokens": 13,
        "output_tokens": 17,
        "total_tokens": 30,
        "cost_usd": 0.02,
    }


def test_grounded_runner_uses_one_llm_schema_repair_without_inventing_defaults(
    tmp_path: Path,
) -> None:
    _prepared_evaluation(tmp_path)
    llm = RepairingLlm()

    result = run_grounded_evaluation(tmp_path, llm)

    assert result["repairs_attempted"] == 1
    assert len(llm.calls) == 2
    assert llm.calls[1]["purpose"] == "accounting_baseline_schema_repair"
    assert "Preserve every accounting fact and amount" in llm.calls[1]["instructions"]
    assert result["usage"]["input_tokens"] == 20
    assert result["usage"]["output_tokens"] == 40
    assert result["usage"]["total_tokens"] == 60


def test_grounded_progress_callback_is_fail_open(tmp_path: Path) -> None:
    _prepared_evaluation(tmp_path)

    def broken_callback(_: dict) -> None:
        raise RuntimeError("telemetry sink unavailable")

    result = run_grounded_evaluation(
        tmp_path,
        FakeLlm(),
        progress_callback=broken_callback,
    )

    assert result["cases"] == 1
    assert result["score_report"]["evaluation_cases"] == 1


def test_production_draft_uses_same_gitc_memory_and_remains_review_only(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    dataset = home / "accounting_brain" / "datasets" / "golden-1"
    attachments = dataset / "attachments"
    attachments.mkdir(parents=True)
    (attachments / "history.txt").write_text(
        "Supplier A materials VAT SAR",
        encoding="utf-8",
    )
    source = home / "inbox" / "new.txt"
    source.parent.mkdir(parents=True)
    source.write_text("Supplier A materials VAT SAR 100.00", encoding="utf-8")

    pair = _reference_row()
    pair["grade"] = "gold"
    pair["input"] = {
        "document": {"date": "2026-01-01"},
        "attachments": pair["source"]["attachments"],
    }
    _write_jsonl(dataset / "pairs.jsonl", [pair])
    llm = CapturingDraftLlm()

    result = prepare_accounting_draft(
        source,
        hermes_home=home,
        datasets_root=home / "accounting_brain" / "datasets",
        output_root=home / "accounting_brain" / "drafts",
        llm=llm,
        top_k=1,
    )

    serialized = json.dumps(llm.calls[0], default=str)
    assert "GITC ACCOUNTING MEMORY" in serialized
    assert "id=7" in serialized
    assert result["production_mode"] == "draft_only"
    assert result["safety"]["odoo_write_performed"] is False
    assert result["safety"]["auto_post"] is False
    assert result["safety"]["human_review_required"] is True
    assert result["safety"]["company_memory_from_validated_gold_only"] is True
