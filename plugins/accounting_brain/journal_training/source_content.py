"""Safe attachment-content policy for Accounting Brain evidence.

Only document/image formats that we intentionally support as accounting source
material are eligible for private-volume hydration. Unknown or executable
content is never downloaded by the dataset pipeline.
"""

from __future__ import annotations

SAFE_EVIDENCE_MIMETYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "text/plain",
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)


def normalize_mimetype(value: object) -> str | None:
    """Return a lowercase MIME type without optional parameters."""
    if value in (None, False, ""):
        return None
    normalized = str(value).split(";", 1)[0].strip().lower()
    return normalized or None


def is_supported_evidence_mimetype(value: object) -> bool:
    """Fail closed for unknown attachment types."""
    normalized = normalize_mimetype(value)
    return normalized in SAFE_EVIDENCE_MIMETYPES if normalized else False
