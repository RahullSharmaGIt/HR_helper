# Task 5 Summary: Restricted Repository Fetcher

## 1. Directory Structure Audit & Corrections
- **Target Path**: Created [`backend/app/services/repository_fetcher.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/repository_fetcher.py) and test suite at [`backend/tests/test_repository_fetcher.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/tests/test_repository_fetcher.py).
- **Service Registration**: Re-exported `fetch_repository`, `read_source_blob`, `RepositoryManifest`, `SourceBlobResult`, and `BlobBudget` in [`backend/app/services/__init__.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/__init__.py).

---

## 2. Completed Scope

### Hardened Bare Clone ([`backend/app/services/repository_fetcher.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/repository_fetcher.py))
- `fetch_repository(repository_url, job_id, runner, allow_file_transport)`:
  - Invokes `git clone --bare --filter=blob:none --single-branch` passing explicit argument lists (never shell strings).
  - Enforces strict security configuration:
    - `-c core.hooksPath=/dev/null` (disables all client hooks).
    - `-c credential.helper=` (disables credential helpers).
    - `GIT_TERMINAL_PROMPT=0` (prevents hanging on interactive prompts).
    - `GIT_CONFIG_NOSYSTEM=1` and `GIT_CONFIG_GLOBAL=/dev/null` (isolates from host Git configuration).
    - `GIT_ALLOW_PROTOCOL=https` (disallows `file://`, `ssh://`, `ext::`, etc. in production).
  - Bounded concurrency with `threading.BoundedSemaphore` (max 4 concurrent clones).
  - Enforces subprocess duration limits (30s) and terminates lingering child processes.
  - Inspects downloaded pack and directory size against `settings.git_max_pack_size_bytes` (50 MB) to counter servers ignoring blob filters.
  - Resolves and verifies 40-character hex HEAD commit SHA.
  - Returns `RepositoryManifest` with workspace key, HEAD SHA, fetch duration, completeness status, and pack size.

### Lazy Blob Retrieval & Budget Enforcement ([`backend/app/services/repository_fetcher.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/app/services/repository_fetcher.py))
- `read_source_blob(repository, commit_sha, path, budget, runner)`:
  - Avoids unrestricted working tree checkouts; loads blobs on demand using `git cat-file`.
  - Checks object size first via `git cat-file -s` before reading content into memory.
  - Skips binary files by inspecting extensions and scanning first 1024 bytes for null bytes.
  - Filters vendor and dependency paths (`node_modules/`, `vendor/`, `.venv/`, `dist/`, etc.).
  - Filters generated artifacts and lockfiles (`*.min.js`, `*.bundle.js`, `package-lock.json`, `Cargo.lock`, etc.).
  - Enforces per-file size limits (200 KB) and cumulative job budgets (`BlobBudget`: 50 files / 2 MB total).

---

## 3. Verification & Test Results
- [`backend/tests/test_repository_fetcher.py`](file:///Users/rahulsharma/Documents/Antigravity%20Apps/DEVIATHON/backend/tests/test_repository_fetcher.py):
  - Verified synthetic local bare clone using `allow_file_transport=True` fixture.
  - Confirmed security arguments and environment isolation flags.
  - Verified rejection of malicious URLs with embedded credentials or invalid hosts.
  - Verified subprocess timeout handling and process cleanup.
  - Verified pack size ceiling enforcement (`GitResourceLimitError`).
  - Verified lazy text blob reading, binary detection, vendor filtering, size ceiling, and cumulative budget limits.
- Test Suite Status: **57 tests passed in 1.48s**; Ruff check: **All checks passed**.
