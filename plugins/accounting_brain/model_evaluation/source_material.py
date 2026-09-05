"""Prepare hydrated Accounting Brain attachments for model inference.

Only files already copied into the private Accounting Brain dataset are read.
The extractor never fetches URLs, never reads arbitrary paths outside the
selected Golden Dataset, and never mutates Odoo.
"""

from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


class SourceMaterialError(RuntimeError):
    """Raised when a hydrated source document cannot be consumed safely."""


_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_TEXT_MIMES = {
    "text/plain",
    "text/csv",
    "application/csv",
    "application/json",
    "application/xml",
    "text/xml",
}
_PDF_MIMES = {"application/pdf"}
_DOCX_MIMES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
_XLSX_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
}
_MAX_TEXT_CHARS = 60_000


def build_model_inputs(
    case_source: dict[str, Any],
    *,
    dataset_root: Path,
) -> list[dict[str, Any]]:
    """Return Hermes PluginLlm structured input blocks for one case."""

    attachments = case_source.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        raise SourceMaterialError("Evaluation case has no source attachments")

    root = dataset_root.expanduser().resolve()
    blocks: list[dict[str, Any]] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        if item.get("content_status") != "downloaded":
            continue
        local_path = item.get("local_path")
        if not isinstance(local_path, str) or not local_path.strip():
            continue
        path = _resolve_private_path(root, local_path)
        mimetype = str(item.get("mimetype") or "").strip().lower()
        filename = str(item.get("filename") or path.name)

        if mimetype in _IMAGE_MIMES:
            blocks.append(
                {
                    "type": "image",
                    "data": path.read_bytes(),
                    "mime_type": mimetype,
                    "file_name": filename,
                }
            )
            continue

        text = _extract_text(path, mimetype)
        if text.strip():
            blocks.append(
                {
                    "type": "text",
                    "text": f"SOURCE DOCUMENT: {filename}\n\n{text[:_MAX_TEXT_CHARS]}",
                }
            )

    if not blocks:
        raise SourceMaterialError(
            "Evaluation case has no model-consumable hydrated source content"
        )
    return blocks


def _resolve_private_path(root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SourceMaterialError("Attachment path escapes the private dataset") from exc
    if not resolved.is_file():
        raise SourceMaterialError(f"Hydrated attachment is missing: {resolved.name}")
    return resolved


def _extract_text(path: Path, mimetype: str) -> str:
    if mimetype in _TEXT_MIMES:
        return path.read_text(encoding="utf-8", errors="replace")
    if mimetype in _PDF_MIMES:
        return _extract_pdf(path)
    if mimetype in _DOCX_MIMES:
        return _extract_docx(path)
    if mimetype in _XLSX_MIMES:
        return _extract_xlsx(path)
    raise SourceMaterialError(f"Unsupported hydrated source type: {mimetype or 'unknown'}")


def _extract_pdf(path: Path) -> str:
    executable = shutil.which("pdftotext")
    if not executable:
        raise SourceMaterialError(
            "PDF extraction requires the production pdftotext runtime dependency"
        )
    completed = subprocess.run(
        [executable, "-layout", str(path), "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise SourceMaterialError(
            f"PDF extraction failed for {path.name}: exit {completed.returncode}"
        )
    return completed.stdout


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise SourceMaterialError(f"Invalid DOCX source: {path.name}") from exc
    root = ElementTree.fromstring(xml_bytes)
    parts = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    return "\n".join(part for part in parts if part.strip())


def _extract_xlsx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            shared = _xlsx_shared_strings(archive)
            sheet_names = sorted(
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            )
            rows: list[str] = []
            for sheet_name in sheet_names[:20]:
                root = ElementTree.fromstring(archive.read(sheet_name))
                for row in root.iter():
                    if not row.tag.endswith("}row"):
                        continue
                    values: list[str] = []
                    for cell in row:
                        if not cell.tag.endswith("}c"):
                            continue
                        cell_type = cell.attrib.get("t")
                        value = next(
                            (
                                child.text
                                for child in cell
                                if child.tag.endswith("}v") and child.text is not None
                            ),
                            "",
                        )
                        if cell_type == "s" and value.isdigit():
                            index = int(value)
                            value = shared[index] if index < len(shared) else value
                        values.append(value)
                    if any(value.strip() for value in values):
                        rows.append("\t".join(values))
                    if sum(len(row) for row in rows) >= _MAX_TEXT_CHARS:
                        return "\n".join(rows)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SourceMaterialError(f"Invalid XLSX source: {path.name}") from exc
    return "\n".join(rows)


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root:
        text = "".join(
            node.text or "" for node in item.iter() if node.tag.endswith("}t")
        )
        values.append(html.unescape(re.sub(r"\s+", " ", text)).strip())
    return values
