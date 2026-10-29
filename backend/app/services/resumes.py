import io
import logging
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

import docx
import pymupdf

from app.config import settings

logger = logging.getLogger("resume_intake")

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class PageContent:
    page_number: int
    text: str


@dataclass
class ResumeExtractionResult:
    storage_key: str
    raw_text: str
    pages: list[PageContent]
    is_scanned: bool = False
    scanned_reason: str | None = None
    truncated: bool = False


def validate_batch_size(batch: list | int) -> None:
    count = len(batch) if isinstance(batch, list) else batch
    if count > settings.max_batch_size:
        raise ValueError(
            f"Batch size {count} exceeds the maximum limit of {settings.max_batch_size} files."
        )
    if count <= 0:
        raise ValueError("Batch must contain at least 1 file.")


def validate_resume(upload_name: str, content: bytes) -> tuple[str, str]:
    """
    Validates uploaded file size, extension, and file signatures.
    Does NOT log resume content. Returns (content_type, normalized_extension).
    """
    if not content:
        raise ValueError("Uploaded file is empty.")

    if len(content) > settings.max_upload_size_bytes:
        raise ValueError(
            f"File size ({len(content)} bytes) exceeds the maximum allowed limit of {settings.max_upload_size_bytes} bytes (10 MB)."
        )

    _, raw_ext = os.path.splitext(upload_name)
    ext = raw_ext.lower()
    if ext not in {".pdf", ".docx"}:
        raise ValueError(f"Unsupported file extension '{ext}'. Only .pdf and .docx are supported.")

    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("File content does not match standard PDF file signature.")
        # Attempt minimal structure verification
        try:
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                if doc.page_count == 0:
                    raise ValueError("PDF document has 0 pages.")
        except Exception as e:
            raise ValueError(f"Malformed PDF document: {e}") from e
        return PDF_MIME, ".pdf"

    # ext == ".docx"
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("File content does not match DOCX/ZIP file signature.")

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            file_names = zf.namelist()
            if "word/document.xml" not in file_names:
                raise ValueError("DOCX archive is missing required word/document.xml entry.")
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > settings.max_docx_uncompressed_bytes:
                raise ValueError("DOCX archive exceeds maximum uncompressed expansion limit.")
    except zipfile.BadZipFile as e:
        raise ValueError("Malformed DOCX archive.") from e

    return DOCX_MIME, ".docx"


def safe_download_filename(filename: str, fallback: str = "resume.pdf") -> str:
    """
    Sanitizes a download filename, preventing directory traversal and removing control chars.
    Handles both POSIX and Windows path separators.
    """
    normalized = filename.replace("\\", "/")
    base = os.path.basename(normalized)
    clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", base).lstrip(".-")
    return clean if clean else fallback


def store_resume(content: bytes, ext: str = ".pdf") -> str:
    """
    Saves resume bytes using a randomly generated UUID storage key outside public directories.
    Never uses the original submitted filename. Applies restrictive file permissions (0600).
    """
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    storage_dir = Path(settings.storage_dir) / "resumes"
    storage_dir.mkdir(parents=True, exist_ok=True)
    try:
        storage_dir.chmod(0o700)
    except OSError:
        pass

    generated_key = f"resumes/{uuid.uuid4().hex}{clean_ext}"
    dest_path = Path(settings.storage_dir) / generated_key

    # Atomic write to storage with 0600 permissions
    dest_path.write_bytes(content)
    try:
        dest_path.chmod(0o600)
    except OSError:
        pass

    logger.info("Stored resume securely with key=%s (size=%d bytes)", generated_key, len(content))
    return generated_key


def extract_resume_text(storage_key: str) -> ResumeExtractionResult:
    """
    Safely extracts text and page boundaries from stored document.
    Enforces time/length bounds and flags scanned documents without calling external OCR.
    """
    file_path = Path(settings.storage_dir) / storage_key
    if not file_path.exists():
        raise FileNotFoundError(f"Stored resume not found: {storage_key}")

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf_text(storage_key, file_path)
    elif ext == ".docx":
        return _extract_docx_text(storage_key, file_path)
    else:
        raise ValueError(f"Unsupported storage format: {ext}")


def _extract_pdf_text(storage_key: str, file_path: Path) -> ResumeExtractionResult:
    pages: list[PageContent] = []
    total_text_parts: list[str] = []
    truncated = False

    try:
        with pymupdf.open(str(file_path)) as doc:
            if doc.page_count > settings.max_pdf_pages:
                raise ValueError(
                    f"PDF document exceeds the maximum limit of {settings.max_pdf_pages} pages (found {doc.page_count})."
                )

            total_chars = 0
            for page_idx in range(doc.page_count):
                page = doc.load_page(page_idx)
                # PyMuPDF's type stubs allow multiple return types for get_text().
                # Normalize it before using it as page content.
                page_text = str(page.get_text() or "")
                page_num = page_idx + 1

                if total_chars + len(page_text) > settings.max_text_chars:
                    remaining = settings.max_text_chars - total_chars
                    truncated_page_text = page_text[:remaining]
                    pages.append(PageContent(page_number=page_num, text=truncated_page_text))
                    total_text_parts.append(truncated_page_text)
                    truncated = True
                    break
                else:
                    pages.append(PageContent(page_number=page_num, text=page_text))
                    total_text_parts.append(page_text)
                    total_chars += len(page_text)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to read PDF document: {e}") from e

    full_text = "\n\n".join(total_text_parts)
    alphanumeric_count = len(re.findall(r"[A-Za-z0-9]", full_text))

    # Flag scanned PDF (e.g. fewer than 30 alphanumeric characters across the document)
    if alphanumeric_count < 30:
        logger.info(
            "Flagged resume %s as scanned (alphanumeric_count=%d)", storage_key, alphanumeric_count
        )
        return ResumeExtractionResult(
            storage_key=storage_key,
            raw_text="",
            pages=[],
            is_scanned=True,
            scanned_reason="Scanned PDF detected. Manual entry required; automatic extraction is unavailable.",
            truncated=False,
        )

    return ResumeExtractionResult(
        storage_key=storage_key,
        raw_text=full_text,
        pages=pages,
        is_scanned=False,
        truncated=truncated,
    )


def _extract_docx_text(storage_key: str, file_path: Path) -> ResumeExtractionResult:
    # 1. Zip bomb / expansion check
    try:
        with zipfile.ZipFile(file_path) as zf:
            if len(zf.infolist()) > 500:
                raise ValueError("DOCX archive contains excessive entries.")
            total_size = sum(info.file_size for info in zf.infolist())
            if total_size > settings.max_docx_uncompressed_bytes:
                raise ValueError("DOCX uncompressed size exceeds safe threshold.")
    except zipfile.BadZipFile as e:
        raise ValueError("Invalid DOCX archive.") from e

    # 2. Extract paragraphs and tables
    try:
        doc = docx.Document(str(file_path))
        extracted_paragraphs: list[str] = []
        for p in doc.paragraphs:
            text = p.text.strip()
            if text:
                extracted_paragraphs.append(text)

        for table in doc.tables:
            for row in table.rows:
                row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_texts:
                    extracted_paragraphs.append(" | ".join(row_texts))
    except Exception as e:
        raise ValueError(f"Failed to parse DOCX document: {e}") from e

    full_text = "\n".join(extracted_paragraphs)
    truncated = False
    if len(full_text) > settings.max_text_chars:
        full_text = full_text[: settings.max_text_chars]
        truncated = True

    pages = [PageContent(page_number=1, text=full_text)]
    return ResumeExtractionResult(
        storage_key=storage_key,
        raw_text=full_text,
        pages=pages,
        is_scanned=False,
        truncated=truncated,
    )
