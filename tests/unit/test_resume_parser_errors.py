from __future__ import annotations

import pytest
from app.resumes.parser import extract_text, extract_text_from_pdf, ResumeParseError

def test_extract_text_empty_input() -> None:
    with pytest.raises(ResumeParseError, match="Empty resume content"):
        extract_text(b"", content_type="text/plain")

def test_extract_text_unsupported_type() -> None:
    with pytest.raises(ResumeParseError, match="Unsupported content type"):
        extract_text(b"some image data", content_type="image/jpeg")

def test_extract_text_from_pdf_malformed() -> None:
    with pytest.raises(ResumeParseError, match="Failed to extract text from PDF"):
        extract_text_from_pdf(b"not a real pdf file!")
