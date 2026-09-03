"""Filesystem adapter for private accounting training datasets."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from plugins.accounting_brain.journal_training.contracts import TrainingDatasetSink
from plugins.accounting_brain.journal_training.models import JournalTrainingPair


class FilesystemTrainingDatasetSink(TrainingDatasetSink):
    """Write normalized evidence under a private Hermes data directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        _chmod_private_dir(self._root)
        self._attachments = self._root / "attachments"
        self._attachments.mkdir(parents=True, exist_ok=True)
        _chmod_private_dir(self._attachments)
        self._pairs_path = self._root / "pairs.jsonl"

    @property
    def root(self) -> Path:
        return self._root

    def write_pair(self, pair: JournalTrainingPair) -> None:
        line = json.dumps(pair.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._pairs_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        _chmod_private_file(self._pairs_path)

    def write_report(self, name: str, payload: dict) -> Path:
        filename = _safe_filename(name or "report.json")
        if not filename.endswith(".json"):
            filename += ".json"
        path = self._root / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _chmod_private_file(path)
        return path

    def write_attachment(
        self,
        *,
        attachment_id: int,
        filename: str,
        content: bytes,
    ) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        clean_name = _safe_filename(filename or f"attachment-{attachment_id}")
        stored_name = f"{int(attachment_id)}-{digest[:12]}-{clean_name}"
        path = self._attachments / stored_name
        if not path.exists():
            path.write_bytes(content)
            _chmod_private_file(path)
        relative = path.relative_to(self._root).as_posix()
        return relative, digest


def _safe_filename(value: str) -> str:
    basename = Path(str(value)).name.strip() or "unnamed"
    cleaned = re.sub(r"[^A-Za-z0-9._()\-]+", "_", basename)
    return cleaned[:180] or "unnamed"


def _chmod_private_dir(path: Path) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _chmod_private_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
