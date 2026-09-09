"""Unit tests for deterministic bounded resume PDF parsing."""

from __future__ import annotations

from typing import Any

import pytest
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.resumes import parser as parser_module
from app.resumes.parser import DeterministicPdfResumeParser


class FakePage:
    def __init__(
        self,
        text: str | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._text = text
        self._error = error

    def extract_text(self) -> str | None:
        if self._error is not None:
            raise self._error
        return self._text


class FakeReader:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages


def _settings(
    *,
    max_pages: int = 25,
    max_characters: int = 200_000,
) -> Settings:
    return Settings(
        resume_max_pages=max_pages,
        resume_max_extracted_characters=max_characters,
    )


def _install_reader(
    monkeypatch: pytest.MonkeyPatch,
    pages: list[FakePage],
) -> None:
    def fake_pdf_reader(
        stream: Any,
        strict: bool = False,
    ) -> FakeReader:
        del stream, strict
        return FakeReader(pages)

    monkeypatch.setattr(
        parser_module,
        "PdfReader",
        fake_pdf_reader,
    )


def test_parser_extracts_text_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage("  First page  "),
            FakePage(""),
            FakePage("Second page"),
        ],
    )

    parser = DeterministicPdfResumeParser(settings=_settings())

    parsed = parser.parse(b"%PDF-test")

    assert parsed.extracted_text == "First page\nSecond page"
    assert parsed.raw_parser_output == {"page_count": 3}
    assert parsed.full_name is None
    assert parsed.skills == []


def test_parser_rejects_document_over_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage("one"),
            FakePage("two"),
            FakePage("three"),
        ],
    )

    parser = DeterministicPdfResumeParser(
        settings=_settings(max_pages=2),
    )

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_PAGE_LIMIT_EXCEEDED"


def test_parser_accepts_document_at_exact_page_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage("one"),
            FakePage("two"),
        ],
    )

    parser = DeterministicPdfResumeParser(
        settings=_settings(max_pages=2),
    )

    parsed = parser.parse(b"%PDF-test")

    assert parsed.extracted_text == "one\ntwo"


def test_parser_rejects_text_over_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage("a" * 500),
            FakePage("b" * 500),
        ],
    )

    parser = DeterministicPdfResumeParser(
        settings=_settings(max_characters=1_000),
    )

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_TEXT_LIMIT_EXCEEDED"


def test_parser_caps_configured_limit_at_public_schema_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(monkeypatch, [FakePage("a" * 200_001)])
    parser = DeterministicPdfResumeParser(
        settings=_settings(max_characters=1_000_000),
    )

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_TEXT_LIMIT_EXCEEDED"


def test_parser_accepts_text_at_exact_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage("1234"),
            FakePage("56789"),
        ],
    )

    parser = DeterministicPdfResumeParser(
        settings=_settings(max_characters=1_000),
    )

    parsed = parser.parse(b"%PDF-test")

    assert parsed.extracted_text == "1234\n56789"
    assert len(parsed.extracted_text) == 10


def test_parser_rejects_pdf_with_no_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(monkeypatch, [])

    parser = DeterministicPdfResumeParser(settings=_settings())

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_PDF_EMPTY"


def test_parser_rejects_pdf_without_readable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage(None),
            FakePage("   "),
        ],
    )

    parser = DeterministicPdfResumeParser(settings=_settings())

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_TEXT_NOT_FOUND"


def test_parser_wraps_reader_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_reader(
        stream: Any,
        strict: bool = False,
    ) -> FakeReader:
        del stream, strict
        raise PdfReadError("broken PDF internals")

    monkeypatch.setattr(
        parser_module,
        "PdfReader",
        failing_reader,
    )

    parser = DeterministicPdfResumeParser(settings=_settings())

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_PDF_INVALID"
    assert "broken PDF internals" not in str(exc_info.value)


def test_parser_wraps_page_extraction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_reader(
        monkeypatch,
        [
            FakePage(
                error=PdfReadError("bad page internals"),
            )
        ],
    )

    parser = DeterministicPdfResumeParser(settings=_settings())

    with pytest.raises(ApplicationError) as exc_info:
        parser.parse(b"%PDF-test")

    assert exc_info.value.code == "RESUME_PDF_INVALID"
    assert "bad page internals" not in str(exc_info.value)
