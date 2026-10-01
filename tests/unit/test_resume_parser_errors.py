from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.resumes.parser import DeterministicPdfResumeParser


@pytest.fixture
def parser() -> DeterministicPdfResumeParser:
    settings = Settings(
        environment="test",
        allowed_hosts=["testserver"],
        cors_allowed_origins=["http://testserver"],
        resume_max_pages=2,
        resume_max_extracted_characters=1000,
    )
    return DeterministicPdfResumeParser(settings=settings)


def test_parse_empty_content(parser: DeterministicPdfResumeParser) -> None:
    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"")
    assert exc.value.code == "RESUME_PDF_INVALID"


def test_parse_invalid_pdf(parser: DeterministicPdfResumeParser) -> None:
    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"not a valid pdf")
    assert exc.value.code == "RESUME_PDF_INVALID"


@patch("app.resumes.parser.PdfReader")
def test_parse_empty_pdf(
    mock_reader_class: MagicMock, parser: DeterministicPdfResumeParser
) -> None:
    mock_reader = mock_reader_class.return_value
    mock_reader.pages = []

    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"dummy")
    assert exc.value.code == "RESUME_PDF_EMPTY"


@patch("app.resumes.parser.PdfReader")
def test_parse_too_many_pages(
    mock_reader_class: MagicMock, parser: DeterministicPdfResumeParser
) -> None:
    mock_reader = mock_reader_class.return_value
    mock_reader.pages = [MagicMock(), MagicMock(), MagicMock()]

    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"dummy")
    assert exc.value.code == "RESUME_PAGE_LIMIT_EXCEEDED"


@patch("app.resumes.parser.PdfReader")
def test_parse_text_limit_exceeded(
    mock_reader_class: MagicMock, parser: DeterministicPdfResumeParser
) -> None:
    mock_reader = mock_reader_class.return_value
    page1 = MagicMock()
    page1.extract_text.return_value = "A" * 1005
    mock_reader.pages = [page1]

    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"dummy")
    assert exc.value.code == "RESUME_TEXT_LIMIT_EXCEEDED"


@patch("app.resumes.parser.PdfReader")
def test_parse_no_text(mock_reader_class: MagicMock, parser: DeterministicPdfResumeParser) -> None:
    mock_reader = mock_reader_class.return_value
    page1 = MagicMock()
    page1.extract_text.return_value = ""
    mock_reader.pages = [page1]

    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"dummy")
    assert exc.value.code == "RESUME_TEXT_NOT_FOUND"


@patch("app.resumes.parser.PdfReader")
def test_parse_success(mock_reader_class: MagicMock, parser: DeterministicPdfResumeParser) -> None:
    mock_reader = mock_reader_class.return_value
    page1 = MagicMock()
    page1.extract_text.return_value = (
        "John Doe\nSoftware Engineer\nPython React DevOps\nSan Francisco, CA"
    )
    mock_reader.pages = [page1]

    result = parser.parse(b"dummy")
    assert result.current_title == "DevOps Engineer"
    assert "California" in result.location
    assert "Python" in result.skills


@patch("app.resumes.parser.PdfReader")
def test_parse_exception_during_read(
    mock_reader_class: MagicMock, parser: DeterministicPdfResumeParser
) -> None:
    mock_reader_class.side_effect = PdfReadError("Corrupt")

    with pytest.raises(ApplicationError) as exc:
        parser.parse(b"dummy")
    assert exc.value.code == "RESUME_PDF_INVALID"
