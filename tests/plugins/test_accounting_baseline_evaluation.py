from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.accounting_brain.model_evaluation.baseline import (
    BaselineEvaluationError,
    run_baseline_evaluation,
)
from plugins.accounting_brain.model_evaluation.hermes_inference import (
    HermesBaselineInference,
    _strict_json_object,
)


def _target(account_code: str = "500100") -> dict:
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
                "account_code": account_code,
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


def _reference_pair(move_id: int) -> dict:
    return {
        "source_move_id": move_id,
        "grade": "gold",
        "input": {
            "document": {
                "move_type": "in_invoice",
                "reference": f"REF-{move_id}",
                "invoice_origin": None,
                "partner": {"id": 44, "name": "Vendor"},
                "journal": {"id": 9, "name": "Vendor Bills"},
                "company": {"id": 1, "name": "GITC"},
                "currency": {"id": 1, "name": "SAR"},
                "amount_untaxed": "100.00",
                "amount_tax": "15.00",
                "amount_total": "115.00",
            }
        },
        "target": _target(),
    }


def _write_ready_dataset(root: Path, *, unsupported: bool = False) -> tuple[Path, dict]:
    dataset = root / "golden-20260903T000000000000Z"
    evaluation = dataset / "evaluation"
    attachments = dataset / "attachments"
    evaluation.mkdir(parents=True)
    attachments.mkdir(parents=True)

    reference_rows = [_reference_pair(index) for index in range(1, 5)]
    holdout_target = _target("HOLDOUT-SECRET-999999")
    holdout_move_id = 99
    all_pairs = [
        *reference_rows,
        {
            "source_move_id": holdout_move_id,
            "grade": "gold",
            "input": {"document": {"company": {"id": 1, "name": "GITC"}}},
            "target": holdout_target,
        },
    ]
    _write_jsonl(dataset / "pairs.jsonl", all_pairs)

    source_path = attachments / ("99-source.xml" if unsupported else "99-source.txt")
    source_path.write_text("Vendor invoice REF-X subtotal 100.00 VAT 15.00 total 115.00 SAR", encoding="utf-8")
    mime = "application/xml" if unsupported else "text/plain"
    input_row = {
        "contract_version": "1.0",
        "case_id": "acct-holdout",
        "source": {
            "attachments": [
                {
                    "filename": source_path.name,
                    "mimetype": mime,
                    "file_size": source_path.stat().st_size,
                    "local_path": f"attachments/{source_path.name}",
                    "content_sha256": "abc",
                    "content_status": "downloaded",
                }
            ]
        },
    }
    truth_row = {
        "contract_version": "1.0",
        "case_id": "acct-holdout",
        "evidence": {
            "source_move_id": holdout_move_id,
            "source_move_name": "BILL/HOLDOUT",
            "event_date": "2026-08-31",
        },
        "target": holdout_target,
    }
    _write_jsonl(evaluation / "evaluation-inputs.jsonl", [input_row])
    _write_jsonl(evaluation / "evaluation-ground-truth.jsonl", [truth_row])
    (evaluation / "evaluation-manifest.json").write_text(
        json.dumps({"ok": True, "stage": "EVALUATION_DATA_READY"}),
        encoding="utf-8",
    )
    return dataset, holdout_target


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


class FakeInference:
    def __init__(self, prediction: dict) -> None:
        self.prediction = prediction
        self.prompts: list[str] = []

    def safe_identity(self) -> dict:
        return {"provider": "fake", "model": "fake-model"}

    def describe_image(self, image_path: Path) -> str:
        return "image evidence"

    def predict_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        self.prompts.append(system_prompt + "\n" + user_prompt)
        return json.loads(json.dumps(self.prediction))


def test_baseline_never_places_holdout_ground_truth_in_model_prompt(tmp_path: Path) -> None:
    _dataset, expected = _write_ready_dataset(tmp_path)
    inference = FakeInference(expected)

    result = run_baseline_evaluation(
        inference,
        tmp_path,
        max_cases=1,
        top_k=2,
        min_consumable_coverage=1.0,
    )

    assert result["ok"] is True
    assert result["stage"] == "BASELINE_FULL_COMPLETE"
    assert result["scores"]["strict_pass_rate"] == 1.0
    assert result["safety"]["model_training_enabled"] is False
    assert result["safety"]["auto_post"] is False
    assert result["leakage_controls"]["retrieval_pool_excludes_all_holdout_move_ids"] is True
    assert inference.prompts
    assert "HOLDOUT-SECRET-999999" not in inference.prompts[0]
    assert "source_move_id" not in inference.prompts[0]
    assert '"500100"' in inference.prompts[0]  # older reference target is allowed RAG evidence


def test_unsupported_source_stays_in_denominator_and_blocks_coverage(tmp_path: Path) -> None:
    _dataset, expected = _write_ready_dataset(tmp_path, unsupported=True)
    inference = FakeInference(expected)

    result = run_baseline_evaluation(
        inference,
        tmp_path,
        max_cases=1,
        min_consumable_coverage=1.0,
    )

    assert result["ok"] is False
    assert result["stage"] == "BLOCKED_BY_MODALITY_COVERAGE"
    assert result["scores"]["cases"] == 1
    assert result["scores"]["strict_pass_rate"] == 0.0
    assert result["source_evidence"]["consumable_coverage"] == 0.0
    assert result["source_evidence"]["unsupported_mimetypes"] == {"application/xml": 1}
    assert inference.prompts == []


def test_strict_json_parser_fails_closed_on_prose() -> None:
    assert _strict_json_object('{"journal_entry": []}') == {"journal_entry": []}
    assert _strict_json_object('```json\n{"journal_entry": []}\n```') == {"journal_entry": []}
    with pytest.raises(BaselineEvaluationError):
        _strict_json_object('Looks good: {"journal_entry": []}')


def test_hermes_adapter_locks_tools_memory_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict = {}

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"model": {"default": "test-model", "provider": "test-provider"}},
    )
    monkeypatch.setattr(
        "hermes_cli.runtime_provider.resolve_runtime_provider",
        lambda **_kwargs: {
            "api_key": "fake-secret",
            "base_url": "https://example.invalid/v1",
            "provider": "test-provider",
            "requested_provider": "test-provider",
            "api_mode": "chat_completions",
            "credential_pool": None,
        },
    )
    monkeypatch.setattr(
        "plugins.accounting_brain.model_evaluation.hermes_inference._safe_vision_identity",
        lambda: ("vision-provider", "vision-model"),
    )

    class FakeAgent:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.suppress_status_output = False
            self.stream_delta_callback = object()
            self.tool_gen_callback = object()

        def run_conversation(self, *, user_message, system_message):
            return {"final_response": '{"journal_entry": []}'}

        def shutdown_memory_provider(self, *_args):
            return None

        def close(self):
            return None

    monkeypatch.setattr("run_agent.AIAgent", FakeAgent)

    adapter = HermesBaselineInference()
    prediction = adapter.predict_json(system_prompt="system", user_prompt="source")

    assert prediction == {"journal_entry": []}
    assert created["enabled_toolsets"] == []
    assert created["skip_memory"] is True
    assert created["skip_context_files"] is True
    assert created["max_iterations"] == 2
    identity = adapter.safe_identity()
    assert identity["tools_enabled"] is False
    assert identity["memory_enabled"] is False
    assert "fake-secret" not in json.dumps(identity)
