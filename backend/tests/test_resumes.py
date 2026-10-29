import io
import logging
import zipfile

import docx
import pymupdf
import pytest

from app.config import settings
from app.services.resumes import (
    extract_resume_text,
    store_resume,
    validate_batch_size,
    validate_resume,
)


def make_synthetic_pdf(
    text: str = "Experienced software engineer with distributed systems focus.",
) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_synthetic_docx(text: str = "Backend developer working on Python microservices.") -> bytes:
    doc = docx.Document()
    doc.add_paragraph(text)
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


def test_validate_resume_valid_pdf():
    pdf_bytes = make_synthetic_pdf()
    mime, ext = validate_resume("resume.pdf", pdf_bytes)
    assert mime == "application/pdf"
    assert ext == ".pdf"


def test_validate_resume_valid_docx():
    docx_bytes = make_synthetic_docx()
    mime, ext = validate_resume("resume.docx", docx_bytes)
    assert "wordprocessingml" in mime
    assert ext == ".docx"


def test_validate_resume_excessive_size():
    oversized = b"a" * (settings.max_upload_size_bytes + 1)
    with pytest.raises(ValueError, match="exceeds the maximum allowed limit"):
        validate_resume("resume.pdf", oversized)


def test_validate_resume_empty_content():
    with pytest.raises(ValueError, match="Uploaded file is empty"):
        validate_resume("resume.pdf", b"")


def test_validate_resume_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported file extension"):
        validate_resume("resume.txt", b"plain text")


def test_validate_resume_extension_signature_mismatch():
    # File named .pdf but containing arbitrary text
    with pytest.raises(ValueError, match="does not match standard PDF file signature"):
        validate_resume("resume.pdf", b"This is not a PDF")

    # File named .docx but containing arbitrary text
    with pytest.raises(ValueError, match="does not match DOCX/ZIP file signature"):
        validate_resume("resume.docx", b"This is not a DOCX")


def test_validate_batch_size():
    validate_batch_size(20)  # ok
    validate_batch_size([f"f{i}.pdf" for i in range(20)])  # ok

    with pytest.raises(ValueError, match="exceeds the maximum limit"):
        validate_batch_size(21)

    with pytest.raises(ValueError, match="must contain at least 1 file"):
        validate_batch_size(0)


def test_store_and_extract_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    sample_text = "Alice Developer\nProjects\nEvent Broker\nDistributed queue in Go"
    pdf_bytes = make_synthetic_pdf(sample_text)

    storage_key = store_resume(pdf_bytes, ext=".pdf")
    assert storage_key.startswith("resumes/")
    assert storage_key.endswith(".pdf")
    assert "Alice" not in storage_key  # Generated UUID, not candidate name

    result = extract_resume_text(storage_key)
    assert not result.is_scanned
    assert "Alice Developer" in result.raw_text
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1


def test_store_and_extract_docx(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    sample_text = "Bob Engineer\nProjects\nCache Store\nIn-memory Redis clone in Rust"
    docx_bytes = make_synthetic_docx(sample_text)

    storage_key = store_resume(docx_bytes, ext=".docx")
    assert storage_key.startswith("resumes/")
    assert storage_key.endswith(".docx")
    assert "Bob" not in storage_key

    result = extract_resume_text(storage_key)
    assert not result.is_scanned
    assert "Bob Engineer" in result.raw_text
    assert len(result.pages) >= 1


def test_extract_scanned_pdf_flags_manual_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    # Blank PDF with no extractable text
    doc = pymupdf.open()
    doc.new_page()
    blank_pdf = doc.tobytes()
    doc.close()

    storage_key = store_resume(blank_pdf, ext=".pdf")
    result = extract_resume_text(storage_key)

    assert result.is_scanned is True
    assert result.scanned_reason is not None
    assert "Scanned PDF detected" in result.scanned_reason


def test_docx_archive_expansion_limit():
    # Create a synthetic docx-like zip with huge uncompressed size but compressed under upload limit
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "a" * (settings.max_docx_uncompressed_bytes + 100))
    data = bio.getvalue()

    with pytest.raises(ValueError, match="exceeds maximum uncompressed expansion limit"):
        validate_resume("bomb.docx", data)


def test_resume_content_not_in_logs(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    secret_text = "SECRET_SUPER_CONFIDENTIAL_RESUME_INFO_XYZ"
    pdf_bytes = make_synthetic_pdf(secret_text)

    with caplog.at_level(logging.DEBUG):
        storage_key = store_resume(pdf_bytes, ext=".pdf")
        extract_resume_text(storage_key)

    for record in caplog.records:
        assert secret_text not in record.message
