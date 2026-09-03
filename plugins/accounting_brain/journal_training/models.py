"""Training-data domain types for historical Odoo journal entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TrainingGrade(str, Enum):
    GOLD = "gold"
    SILVER = "silver"
    REJECTED = "rejected"


@dataclass(frozen=True)
class QualityDecision:
    grade: TrainingGrade
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AttachmentEvidence:
    attachment_id: int
    filename: str
    mimetype: str | None
    file_size: int | None
    checksum: str | None
    local_path: str | None = None
    content_sha256: str | None = None
    content_status: str = "metadata_only"


@dataclass(frozen=True)
class JournalLineTarget:
    account_id: int | None
    account_code: str | None
    account_name: str | None
    partner_id: int | None
    partner_name: str | None
    label: str | None
    debit: str
    credit: str
    balance: str
    amount_currency: str | None
    currency_id: int | None
    currency_name: str | None
    tax_ids: tuple[int, ...]
    analytic_distribution: dict[str, Any] | None


@dataclass(frozen=True)
class JournalTrainingPair:
    source_move_id: int
    source_move_name: str | None
    grade: TrainingGrade
    quality_reasons: tuple[str, ...]
    input: dict[str, Any]
    target: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["grade"] = self.grade.value
        payload["quality_reasons"] = list(self.quality_reasons)
        return payload
