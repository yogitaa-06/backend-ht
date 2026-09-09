"""Deterministic, bounded PDF resume parser."""

from __future__ import annotations

from io import BytesIO
from typing import Protocol

from fastapi import status
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.schemas.resumes import MAX_EXTRACTED_TEXT_CHARACTERS, ParsedResume


class ResumeParser(Protocol):
    """Parser contract used by resume services."""

    def parse(self, content: bytes) -> ParsedResume:
        """Parse validated resume PDF bytes."""
        ...


class DeterministicPdfResumeParser:
    """Extract bounded text from a validated PDF without external services."""

    def __init__(self, *, settings: Settings) -> None:
        self._max_pages = settings.resume_max_pages
        self._max_extracted_characters = min(
            settings.resume_max_extracted_characters,
            MAX_EXTRACTED_TEXT_CHARACTERS,
        )

    def parse(self, content: bytes) -> ParsedResume:
        """Parse PDF bytes into the normalized resume contract."""

        try:
            reader = PdfReader(BytesIO(content), strict=False)
            page_count = len(reader.pages)
        except (PdfReadError, OSError, ValueError) as exc:
            raise _invalid_pdf() from exc

        if page_count == 0:
            raise ApplicationError(
                "RESUME_PDF_EMPTY",
                "The resume PDF contains no pages.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        if page_count > self._max_pages:
            raise ApplicationError(
                "RESUME_PAGE_LIMIT_EXCEEDED",
                "The resume PDF exceeds the allowed page count.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        extracted_parts: list[str] = []
        extracted_length = 0

        try:
            for page in reader.pages:
                page_text = (page.extract_text() or "").strip()

                if not page_text:
                    continue

                separator_length = 1 if extracted_parts else 0
                projected_length = extracted_length + separator_length + len(page_text)

                if projected_length > self._max_extracted_characters:
                    raise ApplicationError(
                        "RESUME_TEXT_LIMIT_EXCEEDED",
                        "The extracted resume text exceeds the allowed size.",
                        status.HTTP_422_UNPROCESSABLE_CONTENT,
                    )

                extracted_parts.append(page_text)
                extracted_length = projected_length
        except ApplicationError:
            raise
        except (PdfReadError, OSError, ValueError) as exc:
            raise _invalid_pdf() from exc

        extracted_text = "\n".join(extracted_parts).strip()

        if not extracted_text:
            raise ApplicationError(
                "RESUME_TEXT_NOT_FOUND",
                "No readable text could be extracted from the resume PDF.",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        return ParsedResume(
            extracted_text=extracted_text,
            raw_parser_output={
                "page_count": page_count,
            },
        )


def _invalid_pdf() -> ApplicationError:
    return ApplicationError(
        "RESUME_PDF_INVALID",
        "The resume PDF could not be parsed.",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
