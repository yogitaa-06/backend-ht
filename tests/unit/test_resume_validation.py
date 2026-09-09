"""Security tests for untrusted resume upload validation."""

from hashlib import sha256

import pytest

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.resumes.validation import validate_resume_upload


def settings(*, max_size: int = 1024) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        resume_max_size_bytes=max_size,
    )


def pdf_bytes(payload: bytes = b"resume") -> bytes:
    return b"%PDF-1.7\n" + payload + b"\n%%EOF"


def test_valid_pdf_returns_backend_calculated_metadata() -> None:
    content = pdf_bytes()

    validated = validate_resume_upload(
        filename="Candidate Resume.PDF",
        content_type="application/pdf",
        content=content,
        settings=settings(),
    )

    assert validated.original_filename == "Candidate Resume.PDF"
    assert validated.content_type == "application/pdf"
    assert validated.size_bytes == len(content)
    assert validated.sha256 == sha256(content).hexdigest()
    assert validated.content == content


def test_browser_path_is_removed_from_display_filename() -> None:
    validated = validate_resume_upload(
        filename=r"C:\fakepath\resume.pdf",
        content_type="application/pdf",
        content=pdf_bytes(),
        settings=settings(),
    )

    assert validated.original_filename == "resume.pdf"


@pytest.mark.parametrize(
    "filename",
    [
        None,
        "",
        "   ",
        "resume.txt",
        "resume.exe.pdf",
        "resume.js.pdf",
        "resume\x00.pdf",
        f"{'x' * 256}.pdf",
    ],
)
def test_unsafe_or_unsupported_filename_is_rejected(
    filename: str | None,
) -> None:
    with pytest.raises(ApplicationError):
        validate_resume_upload(
            filename=filename,
            content_type="application/pdf",
            content=pdf_bytes(),
            settings=settings(),
        )


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "",
        "application/octet-stream",
        "text/plain",
        "image/png",
    ],
)
def test_non_pdf_content_type_is_rejected(
    content_type: str | None,
) -> None:
    with pytest.raises(ApplicationError) as exc_info:
        validate_resume_upload(
            filename="resume.pdf",
            content_type=content_type,
            content=pdf_bytes(),
            settings=settings(),
        )

    assert exc_info.value.status_code == 415


def test_content_type_parameters_are_normalized() -> None:
    validated = validate_resume_upload(
        filename="resume.pdf",
        content_type="Application/PDF; charset=binary",
        content=pdf_bytes(),
        settings=settings(),
    )

    assert validated.content_type == "application/pdf"


def test_empty_file_is_rejected() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        validate_resume_upload(
            filename="resume.pdf",
            content_type="application/pdf",
            content=b"",
            settings=settings(),
        )

    assert exc_info.value.code == "RESUME_FILE_EMPTY"


def test_actual_byte_size_is_enforced() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        validate_resume_upload(
            filename="resume.pdf",
            content_type="application/pdf",
            content=pdf_bytes(b"x" * 1024),
            settings=settings(max_size=1024),
        )

    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "RESUME_FILE_TOO_LARGE"


def test_extension_cannot_replace_pdf_magic_bytes() -> None:
    with pytest.raises(ApplicationError) as exc_info:
        validate_resume_upload(
            filename="resume.pdf",
            content_type="application/pdf",
            content=b"MZ executable content",
            settings=settings(),
        )

    assert exc_info.value.code == "RESUME_FILE_INVALID"


def test_resume_configuration_is_bounded() -> None:
    configured = Settings(
        _env_file=None,
        environment="test",
        resume_storage_bucket="private-resumes",
        resume_max_size_bytes=5 * 1024 * 1024,
        resume_max_pages=25,
        resume_max_extracted_characters=200_000,
    )

    assert configured.resume_storage_bucket == "private-resumes"
    assert configured.resume_max_pages == 25

    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            resume_storage_bucket="Invalid Bucket",
        )

    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            resume_max_size_bytes=100,
        )


"""Security tests for untrusted resume upload validation."""
