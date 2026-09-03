"""Ports for persisting Accounting Brain training datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from plugins.accounting_brain.journal_training.models import JournalTrainingPair


class TrainingDatasetSink(Protocol):
    """Persistence boundary for exported training evidence."""

    @property
    def root(self) -> Path:
        """Dataset root path."""

    def write_pair(self, pair: JournalTrainingPair) -> None:
        """Append one normalized training pair."""

    def write_report(self, name: str, payload: dict) -> Path:
        """Write a JSON report and return its path."""

    def write_attachment(
        self,
        *,
        attachment_id: int,
        filename: str,
        content: bytes,
    ) -> tuple[str, str]:
        """Persist attachment bytes and return relative path and SHA-256."""
