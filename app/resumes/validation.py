"""
Security validation for uploaded resume files.

Purpose:
    Validate untrusted resume upload metadata and bytes before storage or
    parsing.

Does NOT:
    - Trust browser-provided file size.
    - Store uploaded content.
    - Parse the PDF document structure.
    - Generate storage object keys.

Security:
    The backend calculates size and SHA-256 from the received bytes. Original
    filenames are retained only as sanitized display metadata.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePath
from unicodedata import category, normalize

from fastapi import status

from app.core.config import Settings
from app.core.errors import ApplicationError

_PDF_CONTENT_TYPE = "application/pdf"
_PDF_HEADER = b"%PDF-"

_DANGEROUS_INNER_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".exe",
        ".html",
        ".htm",
        ".js",
        ".msi",
        ".ps1",
        ".scr",
        ".svg",
    }
)


@dataclass(frozen=True, slots=True)
class ValidatedResumeUpload:
    """Trusted metadata calculated from validated upload bytes."""

    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    content: bytes


def validate_resume_upload(
    *,
    filename: str | None,
    content_type: str | None,
    content: bytes,
    settings: Settings,
) -> ValidatedResumeUpload:
    """Validate one untrusted PDF upload before storage and parsing."""

    normalized_filename = _normalize_filename(filename)
    normalized_content_type = _normalize_content_type(content_type)

    if normalized_content_type != _PDF_CONTENT_TYPE:
        raise ApplicationError(
            "RESUME_CONTENT_TYPE_UNSUPPORTED",
            "Only PDF resume files are supported.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    if not content:
        raise ApplicationError(
            "RESUME_FILE_EMPTY",
            "The uploaded resume is empty.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    if len(content) > settings.resume_max_size_bytes:
        raise ApplicationError(
            "RESUME_FILE_TOO_LARGE",
            "The uploaded resume exceeds the allowed size.",
            status.HTTP_413_CONTENT_TOO_LARGE,
        )

    if not content.startswith(_PDF_HEADER):
        raise ApplicationError(
            "RESUME_FILE_INVALID",
            "The uploaded file is not a valid PDF resume.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return ValidatedResumeUpload(
        original_filename=normalized_filename,
        content_type=_PDF_CONTENT_TYPE,
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        content=content,
    )


def _normalize_filename(filename: str | None) -> str:
    """Produce bounded display metadata without trusting a client path."""

    if filename is None:
        raise _invalid_filename()

    normalized = normalize("NFKC", filename).strip()

    if not normalized:
        raise _invalid_filename()

    if any(category(character).startswith("C") for character in normalized):
        raise _invalid_filename()

    # Treat both POSIX and Windows separators as untrusted path information.
    basename = normalized.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()

    if not basename or len(basename) > 255:
        raise _invalid_filename()

    path = PurePath(basename)

    if path.suffix.casefold() != ".pdf":
        raise ApplicationError(
            "RESUME_EXTENSION_UNSUPPORTED",
            "The resume filename must use the .pdf extension.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )

    inner_suffixes = {suffix.casefold() for suffix in path.suffixes[:-1]}

    if inner_suffixes & _DANGEROUS_INNER_SUFFIXES:
        raise ApplicationError(
            "RESUME_FILENAME_UNSAFE",
            "The resume filename is not permitted.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    return basename


def _normalize_content_type(content_type: str | None) -> str:
    """Normalize a media type without trusting optional parameters."""

    if content_type is None:
        return ""

    return content_type.split(";", maxsplit=1)[0].strip().casefold()


def _invalid_filename() -> ApplicationError:
    return ApplicationError(
        "RESUME_FILENAME_INVALID",
        "The resume filename is invalid.",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
