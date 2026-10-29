# Task 3 Summary: Resume Intake & Project Extraction

## 1. Directory Structure Audit & Corrections
- **Missing Path Prefix in Prompt**: The prompt specified `Create backend/app/services/resumes.py, project_extraction.py`. The second file lacked the directory prefix; it was correctly routed to [`backend/app/services/project_extraction.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/project_extraction.py) matching the agreed layout `backend/app/{api,models,schemas,services,jobs}`.
- **Service Registration**: Created [`backend/app/services/__init__.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/__init__.py) to expose intake validation, storage, extraction, and project heuristics cleanly.

---

## 2. Completed Scope

### Resume Intake & Storage ([`backend/app/services/resumes.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/resumes.py))
- `validate_resume(upload_name, content)`:
  - Enforces 10 MB per-file upload ceiling and extension validation (`.pdf`, `.docx`).
  - Verifies file signatures: `%PDF-` magic header for PDF; `PK\x03\x04` and `word/document.xml` archive presence for DOCX.
  - Enforces extension agreement against magic bytes.
  - Mitigates zip bomb threats by verifying archive uncompressed expansion size (capped at 30 MB) and entry counts (< 500).
- `validate_batch_size(batch)`:
  - Enforces 1–20 files batch limit per request.
- `store_resume(content, ext)`:
  - Generates secure UUID-based storage keys (`resumes/<uuid>.<ext>`) in private storage outside public directories.
  - Never uses submitted candidate filenames for on-disk file resolution.
- `extract_resume_text(storage_key)`:
  - Parses PDF via PyMuPDF (verifying page counts <= 20) and DOCX via `python-docx`.
  - Enforces bounded extraction text length (<= 100,000 characters).
  - Flags scanned PDFs (insufficient alphanumeric characters) as requiring manual entry without calling external/paid OCR services.
  - **Privacy Guarantee**: Resume text content is never output to application logs.

### Project Suggestion Extraction ([`backend/app/services/project_extraction.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/project_extraction.py))
- `extract_github_urls(text)`:
  - Extracts and normalizes public GitHub repository URLs (`https://github.com/<owner>/<repo>`).
  - Excludes non-repository endpoints (`/features`, `/topics`, `/settings`, etc.) and strips trailing delimiters or `.git` suffixes.
- `extract_project_suggestions(input_data)`:
  - Employs deterministic heuristics to detect project sections and project headers.
  - Preserves source-page numbering when available.
  - Returns suggestions as [`ProjectSuggestion`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/schemas/contracts.py) records for explicit HR selection and confirmation.
  - Never infers identity from filenames or repository author names.

---

## 3. Verification & Test Results
- [`backend/tests/test_resumes.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/tests/test_resumes.py):
  - Valid PDF and DOCX processing.
  - Upload size limit (> 10 MB) rejection.
  - Empty file, invalid extension, and signature mismatch rejections.
  - Batch size enforcement (> 20 rejected).
  - DOCX zip bomb / expansion limit enforcement.
  - Scanned PDF manual entry flag detection.
  - Log verification ensuring zero resume text leakage.
- [`backend/tests/test_project_extraction.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/tests/test_project_extraction.py):
  - Multi-project extraction with explicit GitHub links.
  - Standalone inline repository discovery without explicit "Projects" header.
  - Multi-page source-page reference preservation.
  - Zero false-positive repo links for GitHub system paths.
  - Graceful empty list handling for documents without projects or scanned documents.
- Test Suite Status: **30 tests passed in 0.81s**; Ruff check: **All checks passed**.
