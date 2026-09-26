"""Deterministic, bounded PDF resume parser."""

from __future__ import annotations

from decimal import Decimal
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

        # Basic heuristic parsing for profile population
        text_lower = extracted_text.lower()

        skills: list[str] = []
        skill_keywords = {
            "python": "Python",
            "react": "React",
            "devops": "DevOps",
            "sql": "SQL",
            "aws": "AWS",
            "azure": "Azure",
            "gcp": "GCP",
            "docker": "Docker",
            "kubernetes": "Kubernetes",
            "javascript": "JavaScript",
            "typescript": "TypeScript",
            "java": "Java",
            "c++": "C++",
            "c#": "C#",
            "ruby": "Ruby",
            "go": "Go",
            "rust": "Rust",
            "php": "PHP",
            "html": "HTML",
            "css": "CSS",
            "node": "Node.js",
            "django": "Django",
            "flask": "Flask",
            "spring": "Spring",
            "linux": "Linux",
            "sre": "SRE",
            "cloud": "Cloud Computing",
        }
        for kw, skill_name in skill_keywords.items():
            if kw in text_lower:
                skills.append(skill_name)

        location = "Remote"
        if "new york" in text_lower or "ny" in text_lower.split():
            location = "New York, NY"
        elif "california" in text_lower or "ca" in text_lower.split():
            location = "California"
        elif "texas" in text_lower or "tx" in text_lower.split():
            location = "Texas"
        elif "london" in text_lower:
            location = "London, UK"
        elif "san francisco" in text_lower:
            location = "San Francisco, CA"
        elif "seattle" in text_lower:
            location = "Seattle, WA"
        elif "austin" in text_lower:
            location = "Austin, TX"

        current_title = "Software Engineer"
        if "devops" in text_lower or "site reliability" in text_lower:
            current_title = "DevOps Engineer"
        elif "frontend" in text_lower or "front end" in text_lower:
            current_title = "Frontend Engineer"
        elif "backend" in text_lower or "back end" in text_lower:
            current_title = "Backend Engineer"
        elif "fullstack" in text_lower or "full stack" in text_lower:
            current_title = "Full Stack Engineer"
        elif "data scientist" in text_lower:
            current_title = "Data Scientist"
        elif "product manager" in text_lower:
            current_title = "Product Manager"

        yoe = Decimal("2.0")
        if "senior" in text_lower or "staff" in text_lower or "principal" in text_lower:
            yoe = Decimal("6.0")
        elif "lead" in text_lower or "manager" in text_lower or "director" in text_lower:
            yoe = Decimal("10.0")

        return ParsedResume(
            full_name=None,
            current_title=current_title,
            location=location,
            skills=skills[:10],
            years_of_experience=yoe,
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
