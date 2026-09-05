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


def test_baseline_runner_requires_ready_manifest(tmp_path: Path) -> None:
    dataset = _prepared_evaluation(tmp_path)
    manifest_path = dataset / "evaluation" / "evaluation-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ok"] = False
    manifest["stage"] = "BLOCKED_BY_SOURCE_EVIDENCE"
    _write_json(manifest_path, manifest)

    with pytest.raises(BaselineEvaluationError, match="Prepare leakage-safe"):
        run_baseline_evaluation(tmp_path, FakeLlm(_target()))
