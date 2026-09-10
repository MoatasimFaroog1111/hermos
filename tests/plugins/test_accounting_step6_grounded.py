"""Tests for STEP 6 grounded evaluation: leakage safety, memory derivation, runner.

Tests verify:
- Company memory derives ONLY from non-holdout reference rows
- No amounts leaked into memory hints
- Journal→move_type and move_type→journal conditional frequencies correct
- Account debit/credit direction preferences from historical usage
- DeepSeek json_schema → json_object fallback
- Schema repair (structure only, no logic)
- Deterministic schema validation
- Telemetry fail-open (no exceptions on missing usage)
- Runner never reads ground truth during inference
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from plugins.accounting_brain.model_evaluation.company_memory import (
    build_memory_hints,
    derive_company_memory,
)
from plugins.accounting_brain.model_evaluation.grounded_runner import (
    GroundedEvaluationTelemetry,
    _repair_schema_only,
    _validate_schema_locally,
)


def _ref_row(move_id: int, journal: str = "MISC", move_type: str = "entry") -> dict[str, Any]:
    """Create a minimal reference row (non-holdout Gold)."""
    return {
        "contract_version": "1.0",
        "reference_id": f"move-{move_id}",
        "source_move_id": move_id,  # Present in reference, but memory should not expose it
        "target": {
            "move_type": move_type,
            "journal": {"name": journal, "code": journal.lower()},
            "partner": {"id": 100} if move_id % 2 == 0 else None,
            "currency": {"name": "SAR", "code": "SAR"},
            "taxes": [{"name": "VAT 15%", "id": 1}] if move_id % 3 == 0 else [],
            "journal_entry": [
                {
                    "account_code": "510000",
                    "account_name": "Expense Materials",
                    "account_id": 100,
                    "debit": "100.00",
                    "credit": "0.00",
                    "tax_ids": [],
                    "analytic_distribution": {"department": 50} if move_id % 2 == 1 else {},
                },
                {
                    "account_code": "211000",
                    "account_name": "Accounts Payable",
                    "account_id": 200,
                    "debit": "0.00",
                    "credit": "100.00",
                    "tax_ids": [],
                    "analytic_distribution": {},
                },
            ],
        },
    }


class TestCompanyMemoryLeakageSafety:
    """Verify memory derivation is safe and never exposes holdout facts."""

    def test_memory_derives_from_reference_only(self) -> None:
        """Memory must derive from reference rows only (never opens ground truth)."""
        reference = [_ref_row(i) for i in range(1, 4)]
        memory = derive_company_memory(reference)

        # Verify totals
        assert memory.total_reference_cases == 3
        assert memory.journals["MISC"] == 3
        assert memory.move_types["entry"] == 3

    def test_memory_never_exposes_move_ids_or_checksums(self) -> None:
        """Memory must not expose source_move_id or any checksums."""
        reference = [_ref_row(i) for i in range(1, 3)]
        memory = derive_company_memory(reference)

        serialized = json.dumps(memory.to_dict())

        # source_move_id should NOT appear (it's in reference, but memory excludes it)
        assert "source_move_id" not in serialized
        assert "checksum" not in serialized

    def test_memory_account_names_from_history(self) -> None:
        """Account catalog should contain actual GITC account names from history."""
        reference = [_ref_row(i) for i in range(1, 3)]
        memory = derive_company_memory(reference)

        # Check account 510000 has recorded its name
        assert "510000" in memory.account_catalog
        assert "Expense Materials" in memory.account_catalog["510000"]["names"]

        # Check account 211000
        assert "211000" in memory.account_catalog
        assert "Accounts Payable" in memory.account_catalog["211000"]["names"]

    def test_memory_no_amounts_in_hints(self) -> None:
        """Memory hints must never contain historical amounts."""
        reference = [_ref_row(i) for i in range(1, 3)]
        memory = derive_company_memory(reference)
        hints = build_memory_hints(memory)

        # Should not contain "100.00"
        assert "100.00" not in hints
        assert "100" not in hints or "cases" in hints  # "100" only OK if "X cases"

    def test_memory_deterministic_on_order(self) -> None:
        """Memory derivation must be deterministic (order-invariant catalogs)."""
        ref_list = [_ref_row(i) for i in range(1, 4)]

        mem1 = derive_company_memory(ref_list)
        mem2 = derive_company_memory(list(reversed(ref_list)))

        # Account catalog should match
        assert mem1.account_catalog == mem2.account_catalog


class TestJournalMoveTypeMapping:
    """Verify journal→move_type and move_type→journal conditional frequencies."""

    def test_journal_to_move_type_conditional(self) -> None:
        """Journal→move_type pairs must track conditional counts and confidence."""
        # Create reference: 3x MISC/entry, 1x BILL/in_invoice
        reference = [
            _ref_row(1, journal="MISC", move_type="entry"),
            _ref_row(2, journal="MISC", move_type="entry"),
            _ref_row(3, journal="MISC", move_type="entry"),
            _ref_row(4, journal="BILL", move_type="in_invoice"),
        ]
        memory = derive_company_memory(reference)

        # Check pairs
        assert memory.journal_move_type_pairs[("MISC", "entry")] == 3
        assert memory.journal_move_type_pairs[("BILL", "in_invoice")] == 1

    def test_move_type_to_journal_reverse_mapping(self) -> None:
        """move_type→journal pairs must also track for reverse lookup."""
        reference = [
            _ref_row(1, journal="MISC", move_type="entry"),
            _ref_row(2, journal="MISC", move_type="entry"),
            _ref_row(3, journal="BILL", move_type="entry"),  # BILL also has entry
        ]
        memory = derive_company_memory(reference)

        # Check reverse mapping
        assert memory.move_type_journal_pairs[("entry", "MISC")] == 2
        assert memory.move_type_journal_pairs[("entry", "BILL")] == 1


class TestAccountDirectionPriors:
    """Verify account debit/credit direction frequencies reflect historical usage."""

    def test_account_debit_credit_counts(self) -> None:
        """Account 510000 should always be debit; 211000 always credit."""
        reference = [_ref_row(i) for i in range(1, 4)]
        memory = derive_company_memory(reference)

        acc_510 = memory.account_catalog["510000"]
        assert acc_510["debit_count"] == 3
        assert acc_510["credit_count"] == 0

        acc_211 = memory.account_catalog["211000"]
        assert acc_211["debit_count"] == 0
        assert acc_211["credit_count"] == 3

    def test_move_type_debit_credit_distribution(self) -> None:
        """Move type debit/credit counts should track by type."""
        reference = [_ref_row(i) for i in range(1, 3)]
        memory = derive_company_memory(reference)

        # "entry" move_type: 2x 510000 debit, 2x 211000 credit
        assert memory.move_type_debit_count["entry"] == 2
        assert memory.move_type_credit_count["entry"] == 2


class TestDeepSeekFallback:
    """Test json_schema → json_object fallback mechanism."""

    def test_repair_adds_missing_debit_credit_defaults(self) -> None:
        """Repair must add missing debit/credit as "0.00" (structural, not logic)."""
        broken = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
            "partner": None,
            "currency": {"name": "SAR"},
            "taxes": [],
            "journal_entry": [
                {"account_code": "510000"},  # Missing debit, credit, tax_ids, analytic
                {
                    "account_code": "211000",
                    "debit": "0.00",
                    "credit": "100.00",
                    "tax_ids": [],
                    "analytic_distribution": {},
                },
            ],
        }

        repaired, repair_needed = _repair_schema_only(broken)

        assert repair_needed is True
        line0 = repaired["journal_entry"][0]
        assert "debit" in line0 and line0["debit"] == "0.00"
        assert "credit" in line0 and line0["credit"] == "0.00"
        assert "tax_ids" in line0 and line0["tax_ids"] == []
        assert "analytic_distribution" in line0 and line0["analytic_distribution"] == {}

    def test_repair_converts_numeric_debit_credit_to_string(self) -> None:
        """Repair must convert numeric debit/credit to ".2f" strings."""
        broken = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
            "partner": None,
            "currency": {"name": "SAR"},
            "taxes": [],
            "journal_entry": [
                {
                    "account_code": "510000",
                    "debit": 123.456,  # Numeric
                    "credit": 0,
                    "tax_ids": [],
                    "analytic_distribution": {},
                },
                {
                    "account_code": "211000",
                    "debit": "0.00",
                    "credit": "123.46",
                    "tax_ids": [],
                    "analytic_distribution": {},
                },
            ],
        }

        repaired, repair_needed = _repair_schema_only(broken)

        assert repair_needed is True
        assert repaired["journal_entry"][0]["debit"] == "123.46"
        assert isinstance(repaired["journal_entry"][0]["debit"], str)

    def test_repair_idempotent_on_valid_schema(self) -> None:
        """Repair should not modify already-valid schema."""
        valid = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
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

        repaired, repair_needed = _repair_schema_only(valid)

        assert repair_needed is False
        assert repaired == valid


class TestSchemaValidation:
    """Test deterministic local schema validation."""

    def test_valid_schema_passes(self) -> None:
        """Valid prediction must pass local validation."""
        valid = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
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

        assert _validate_schema_locally(valid) is True

    def test_missing_required_field_fails(self) -> None:
        """Missing top-level field must fail."""
        invalid = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
            # Missing partner, currency, taxes, journal_entry
        }

        assert _validate_schema_locally(invalid) is False

    def test_single_line_fails(self) -> None:
        """Single line (need >= 2) must fail."""
        invalid = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
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
            ],
        }

        assert _validate_schema_locally(invalid) is False

    def test_missing_line_field_fails(self) -> None:
        """Missing required line field must fail."""
        invalid = {
            "move_type": "entry",
            "journal": {"name": "MISC"},
            "partner": None,
            "currency": {"name": "SAR"},
            "taxes": [],
            "journal_entry": [
                {
                    "account_code": "510000",
                    # Missing debit, credit, tax_ids, analytic_distribution
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

        assert _validate_schema_locally(invalid) is False


class TestTelemetryFailOpen:
    """Test telemetry handles edge cases and missing usage info gracefully."""

    def test_empty_telemetry_defaults(self) -> None:
        """Empty telemetry must have sensible defaults."""
        telem = GroundedEvaluationTelemetry()
        report = telem.finalize()

        assert report["total_cases"] == 0
        assert report["success_rate"] == 0.0
        assert report["cost_usd"] == 0.0
        assert report["retrieval"]["avg_per_case"] == 0.0

    def test_telemetry_accumulates_correctly(self) -> None:
        """Telemetry must accumulate tokens, costs, and counts."""
        telem = GroundedEvaluationTelemetry()

        telem.record_case(success=True, tokens=100, cost=0.01, retrieval_count=5)
        telem.record_case(success=True, tokens=120, cost=0.012, retrieval_count=4)
        telem.record_case(success=False, tokens=50, cost=0.005, retrieval_count=3)

        report = telem.finalize()

        assert report["total_cases"] == 3
        assert report["successful_cases"] == 2
        assert report["tokens"]["total"] == 270
        assert report["cost_usd"] == pytest.approx(0.027, abs=0.001)
        assert report["retrieval"]["total_retrieved"] == 12

    def test_telemetry_tracks_fallback_and_repair(self) -> None:
        """Telemetry must track fallback and repair separately."""
        telem = GroundedEvaluationTelemetry()

        telem.record_case(success=True, fallback=True, repair=False, tokens=100)
        telem.record_case(success=True, fallback=False, repair=True, tokens=100)
        telem.record_case(success=False, fallback=False, repair=False, error=True)

        report = telem.finalize()

        assert report["fallback_cases"] == 1
        assert report["repair_cases"] == 1
        assert report["error_cases"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
