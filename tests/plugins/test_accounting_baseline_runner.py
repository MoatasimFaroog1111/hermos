from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from plugins.accounting_brain.model_evaluation.baseline_runner import (
    BaselineEvaluationError,
    run_baseline_evaluation,
)
from plugins.accounting_brain.model_evaluation.source_material import (
    SourceMaterialError,
    build_model_inputs,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _target() -> dict:
    return {
        "move_type": "entry",
        "journal": {"name": "Miscellaneous"},
        "partner": None,
        "currency": {"name": "SAR"},
        "taxes": [],
        "journal_entry": [
            {
                "account_code": "510000",
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


def _invalid_target() -> dict:
    prediction = _target()
    prediction["journal_entry"][0].pop("analytic_distribution")
    return prediction


class FakeLlm:
    def __init__(self, prediction: dict) -> None:
        self.prediction = prediction
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed=self.prediction,
            provider="fake",
            model="fake-accountant",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
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
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                cost_usd=0.01,
            ),
        )


class SchemaRepairingLlm:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        prediction = (
            _target()
            if kwargs.get("purpose") == "accounting_baseline_schema_repair"
            else _invalid_target()
        )
        return SimpleNamespace(
            parsed=prediction,
            provider="deepseek",
            model="deepseek-v4-pro",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                cost_usd=0.01,
            ),
        )


class SchemaRepairStillInvalidLlm(SchemaRepairingLlm):
    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed=_invalid_target(),
            provider="deepseek",
            model="deepseek-v4-pro",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                cost_usd=0.01,
            ),
        )


def _prepared_evaluation(tmp_path: Path) -> Path:
    dataset = tmp_path / "golden-20260905T000000Z"
    evaluation = dataset / "evaluation"
    attachments = dataset / "attachments"
    evaluation.mkdir(parents=True)
    attachments.mkdir(parents=True)
    source = attachments / "invoice.txt"
    source.write_text("Office supplies total SAR 100.00", encoding="utf-8")

    manifest = {
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
    }
    _write_json(evaluation / "evaluation-manifest.json", manifest)
    _write_jsonl(
        evaluation / "evaluation-inputs.jsonl",
        [
            {
                "contract_version": "1.0",
                "case_id": "case-1",
                "source": {
                    "attachments": [
                        {
                            "filename": "invoice.txt",
                            "mimetype": "text/plain",
                            "local_path": "attachments/invoice.txt",
                            "content_status": "downloaded",
                        }
                    ]
                },
            }
        ],
    )
    _write_jsonl(
        evaluation / "evaluation-ground-truth.jsonl",
        [
            {
                "contract_version": "1.0",
                "case_id": "case-1",
                "target": _target(),
            }
        ],
    )
    return dataset


def test_source_material_blocks_path_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    source = {
        "attachments": [
            {
                "filename": "outside.txt",
                "mimetype": "text/plain",
                "local_path": str(outside),
                "content_status": "downloaded",
            }
        ]
    }

    with pytest.raises(SourceMaterialError, match="escapes"):
        build_model_inputs(source, dataset_root=tmp_path)


def test_baseline_runner_never_sends_ground_truth_to_fake_llm(tmp_path: Path) -> None:
    dataset = _prepared_evaluation(tmp_path)
    llm = FakeLlm(_target())

    result = run_baseline_evaluation(tmp_path, llm)

    assert result["cases"] == 1
    assert result["providers"] == ["fake"]
    assert result["models"] == ["fake-accountant"]
    assert llm.calls
    serialized_call = json.dumps(llm.calls[0], default=str)
    assert "ground-truth" not in serialized_call
    assert "510000" not in serialized_call
    assert (dataset / "evaluation" / "evaluation-predictions.jsonl").is_file()


def test_baseline_runner_falls_back_to_json_object_when_schema_format_is_rejected(
    tmp_path: Path,
) -> None:
    _prepared_evaluation(tmp_path)
    llm = JsonSchemaRejectingLlm(_target())

    result = run_baseline_evaluation(tmp_path, llm)

    assert result["cases"] == 1
    assert result["providers"] == ["deepseek"]
    assert result["models"] == ["deepseek-v4-pro"]
    assert len(llm.calls) == 2
    assert llm.calls[0]["json_schema"] is not None
    assert llm.calls[1]["json_schema"] is None
    assert llm.calls[1]["json_mode"] is True
    assert "JSON schema" in llm.calls[1]["instructions"]


def test_baseline_runner_repairs_one_schema_invalid_prediction_without_ground_truth(
    tmp_path: Path,
) -> None:
    _prepared_evaluation(tmp_path)
    llm = SchemaRepairingLlm()

    result = run_baseline_evaluation(tmp_path, llm)

    assert result["cases"] == 1
    assert result["providers"] == ["deepseek"]
    assert result["models"] == ["deepseek-v4-pro"]
    assert result["usage"]["total_tokens"] == 60
    assert len(llm.calls) == 2
    repair_call = llm.calls[1]
    assert repair_call["purpose"] == "accounting_baseline_schema_repair"
    assert repair_call["json_schema"] is None
    assert repair_call["json_mode"] is True
    assert "analytic_distribution" in repair_call["instructions"]
    serialized_repair = json.dumps(repair_call, default=str)
    assert "ground-truth" not in serialized_repair
    assert "Office supplies" not in serialized_repair


def test_baseline_runner_reports_schema_path_after_repair_still_fails(
    tmp_path: Path,
) -> None:
    _prepared_evaluation(tmp_path)
    llm = SchemaRepairStillInvalidLlm()

    with pytest.raises(BaselineEvaluationError) as exc_info:
        run_baseline_evaluation(tmp_path, llm)

    message = str(exc_info.value)
    assert "case case-1" in message
    assert "$.journal_entry[0]" in message
    assert "analytic_distribution" in message
    assert len(llm.calls) == 2


def test_baseline_runner_emits_progress_without_exposing_ground_truth(tmp_path: Path) -> None:
    _prepared_evaluation(tmp_path)
    llm = SchemaRepairingLlm()
    events: list[dict] = []

    result = run_baseline_evaluation(tmp_path, llm, progress_callback=events.append)

    assert result["cases"] == 1
    phases = [event["phase"] for event in events]
    assert phases == [
        "initialized",
        "case_started",
        "schema_repair",
        "case_completed",
        "scoring",
        "completed",
    ]
    completed = next(event for event in events if event["phase"] == "case_completed")
    assert completed["completed_cases"] == 1
    assert completed["total_cases"] == 1
    assert completed["current_case"] == "case-1"
    assert completed["repairs_attempted"] == 1
    assert completed["providers"] == ["deepseek"]
    assert completed["models"] == ["deepseek-v4-pro"]
    serialized_events = json.dumps(events, default=str)
    assert "ground-truth" not in serialized_events
    assert "510000" not in serialized_events
    assert "Office supplies" not in serialized_events


def test_baseline_runner_ignores_progress_callback_failures(tmp_path: Path) -> None:
    _prepared_evaluation(tmp_path)

    def broken_callback(_event: dict) -> None:
        raise RuntimeError("telemetry sink unavailable")

    result = run_baseline_evaluation(
        tmp_path,
        FakeLlm(_target()),
        progress_callback=broken_callback,
    )

    assert result["cases"] == 1


def test_baseline_runner_requires_ready_manifest(tmp_path: Path) -> None:
    dataset = _prepared_evaluation(tmp_path)
    manifest_path = dataset / "evaluation" / "evaluation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ok"] = False
    manifest["stage"] = "BLOCKED_BY_SOURCE_EVIDENCE"
    _write_json(manifest_path, manifest)

    with pytest.raises(BaselineEvaluationError, match="Prepare leakage-safe"):
        run_baseline_evaluation(tmp_path, FakeLlm(_target()))
