from __future__ import annotations

import json
from pathlib import Path

from plugins.accounting_brain.model_evaluation.reference_pool import (
    prepare_reference_pool,
)
from plugins.accounting_brain.model_evaluation.retrieval import (
    retrieve_historical_examples,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _pair(
    move_id: int,
    filename: str,
    checksum: str,
    local_path: str,
    account_code: str,
) -> dict:
    return {
        "source_move_id": move_id,
        "source_move_name": f"MISC/{move_id}",
        "grade": "gold",
        "input": {
            "document": {
                "date": f"2026-01-{move_id:02d}",
                "company": {"id": 1, "name": "Guardian"},
            },
            "attachments": [
                {
                    "filename": filename,
                    "mimetype": "text/plain",
                    "checksum": checksum,
                    "content_sha256": checksum,
                    "local_path": local_path,
                    "content_status": "downloaded",
                }
            ],
        },
        "target": {
            "move_type": "entry",
            "journal": {"id": 5, "name": "Miscellaneous"},
            "partner": None,
            "currency": {"id": 1, "name": "SAR"},
            "taxes": [],
            "journal_entry": [
                {
                    "account_code": account_code,
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
        },
    }


def test_reference_pool_excludes_holdout_move_and_checksum(tmp_path: Path) -> None:
    dataset = tmp_path / "golden-20260905T000000Z"
    evaluation = dataset / "evaluation"
    attachments = dataset / "attachments"
    evaluation.mkdir(parents=True)
    attachments.mkdir(parents=True)

    for name, text in (
        ("office.txt", "office supplies printer paper"),
        ("holdout.txt", "office supplies printer paper latest"),
        ("duplicate.txt", "duplicate of latest invoice"),
    ):
        (attachments / name).write_text(text, encoding="utf-8")

    pairs = [
        _pair(1, "office.txt", "aaa", "attachments/office.txt", "510100"),
        _pair(2, "holdout.txt", "bbb", "attachments/holdout.txt", "510200"),
        _pair(3, "duplicate.txt", "bbb", "attachments/duplicate.txt", "510300"),
    ]
    _write_jsonl(dataset / "pairs.jsonl", pairs)
    _write_json(
        evaluation / "evaluation-manifest.json",
        {
            "ok": True,
            "stage": "EVALUATION_DATA_READY",
            "contract_version": "1.0",
        },
    )
    _write_jsonl(
        evaluation / "evaluation-inputs.jsonl",
        [
            {
                "case_id": "case-2",
                "source": {
                    "attachments": pairs[1]["input"]["attachments"],
                },
            }
        ],
    )
    _write_jsonl(
        evaluation / "evaluation-ground-truth.jsonl",
        [
            {
                "case_id": "case-2",
                "evidence": {"source_move_id": 2},
                "target": pairs[1]["target"],
            }
        ],
    )

    report = prepare_reference_pool(tmp_path)
    rows = [
        json.loads(line)
        for line in (evaluation / "evaluation-reference.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert report["reference_cases"] == 1
    assert report["excluded_holdout_moves"] == 1
    assert report["excluded_exact_checksum_matches"] == 1
    assert [row["source_move_id"] for row in rows] == [1]
    assert rows[0]["target"]["journal_entry"][0]["account_code"] == "510100"


def test_retrieval_ranks_matching_historical_document(tmp_path: Path) -> None:
    dataset = tmp_path / "golden-20260905T000000Z"
    attachments = dataset / "attachments"
    attachments.mkdir(parents=True)
    (attachments / "query.txt").write_text(
        "printer paper office supplies toner",
        encoding="utf-8",
    )
    (attachments / "office.txt").write_text(
        "office supplies printer paper stationery",
        encoding="utf-8",
    )
    (attachments / "diesel.txt").write_text(
        "diesel fuel truck project",
        encoding="utf-8",
    )

    query = {
        "attachments": [
            {
                "filename": "query.txt",
                "mimetype": "text/plain",
                "local_path": "attachments/query.txt",
                "content_status": "downloaded",
            }
        ]
    }
    references = [
        {
            "reference_id": "office",
            "event_date": "2026-01-01",
            "source": {
                "attachments": [
                    {
                        "filename": "office.txt",
                        "mimetype": "text/plain",
                        "local_path": "attachments/office.txt",
                        "content_status": "downloaded",
                    }
                ]
            },
            "target": _pair(
                1,
                "office.txt",
                "aaa",
                "attachments/office.txt",
                "510100",
            )["target"],
        },
        {
            "reference_id": "diesel",
            "event_date": "2026-01-02",
            "source": {
                "attachments": [
                    {
                        "filename": "diesel.txt",
                        "mimetype": "text/plain",
                        "local_path": "attachments/diesel.txt",
                        "content_status": "downloaded",
                    }
                ]
            },
            "target": _pair(
                2,
                "diesel.txt",
                "ccc",
                "attachments/diesel.txt",
                "410003",
            )["target"],
        },
    ]

    result = retrieve_historical_examples(
        query,
        references,
        dataset_root=dataset,
        top_k=1,
    )

    assert len(result) == 1
    assert result[0]["reference_id"] == "office"
    assert result[0]["historical_posting"]["journal_entry"][0]["account_code"] == "510100"
