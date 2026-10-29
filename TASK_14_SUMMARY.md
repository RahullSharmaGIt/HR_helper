# Task 14 Summary: Privacy, Isolation, and Retention

## Overview
Implemented retention policies, worker isolation boundaries, structured log redaction, security headers, cross-origin protection, safe file handling, and focused security tests across backend and deployment configurations.

## Deliverables & Key Changes

### 1. `backend/app/services/retention.py`
- **Configurable Retention**: Enforces retention threshold (default 7 days via `settings.retention_days`).
- **Unified Deletion Logic**: Reuses deletion pipeline:
  - Cancels active (queued / running) analysis jobs via `cancel_analysis`.
  - Removes physical upload files from storage (`resume.storage_key`).
  - Purges temporary Git workspaces (`workspaces/job_{id}_*`).
  - Deletes candidate database record with automatic cascade to projects, repository selections, analysis jobs, and analysis results.
- **Dual Operating Modes**:
  - `dry_run=True`: Scans and reports counts of expired candidates, resumes, active jobs, and workspaces without mutating state.
  - `dry_run=False`: Executes atomic database deletion and disk cleanup.
- **Idempotent**: Successive cleanup executions produce zero side effects or duplicate operations.

### 2. `scripts/cleanup.py`
- Runnable CLI script parsing `--days`, `--dry-run`, and `--execute`.
- Runs `run_retention_cleanup`, prints formatted summary, and exits with status code 0.

### 3. `backend/app/services/log_redaction.py`
- `SensitiveDataRedactionFilter`: Intercepts log records to redact:
  - GitHub personal access tokens (`ghp_*`, `github_pat_*`).
  - Bearer authentication tokens.
  - Session cookies (`session_token=*`).
  - Candidate email addresses (`[REDACTED_EMAIL]`).
  - Password and secret fields.
- Auto-attaches to Python root logger and all handlers on application startup.

### 4. `compose.yaml` (Worker Isolation & Constraints)
- **No Docker Socket**: `/var/run/docker.sock` is not mounted.
- **No Host Mounts**: Removed host directory bind mounts from the worker service.
- **No Unneeded Secrets**: Stripped `SECRET_KEY` and admin authentication secrets from worker environment.
- **Privilege Hardening**: Configured `privileged: false`, `security_opt: ["no-new-privileges:true"]`, `cap_drop: ["ALL"]`.
- **Resource & Process Limits**: Added `cpus: "2.0"`, `memory: 1G`, `pids_limit: 100`.
- **Workspace Isolation**: Configured ephemeral `tmpfs` workspace mount (`/tmp/git_workspaces:size=512M,mode=1777`).

### 5. `backend/app/main.py` & Security Hardening
- `SecurityHeadersMiddleware`: Emits `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy`, `Referrer-Policy: strict-origin-when-cross-origin`, and `Permissions-Policy`.
- `CrossOriginProtectionMiddleware`: Blocks state-mutating requests (`POST`, `PUT`, `PATCH`, `DELETE`) from non-whitelisted cross-origin origins with 403 `INVALID_ORIGIN`.
- Restrictive storage permissions (`0o600` for files, `0o700` for storage directory) in `store_resume`.
- `safe_download_filename`: Sanitizes path traversal characters across both POSIX and Windows separators.
- Protected resume download endpoint (`/api/v1/resumes/{id}/download`) with authentication and path traversal boundary checks.

### 6. Tests (`test_security.py` & `test_retention.py`)
- **`backend/tests/test_retention.py`** (5 tests):
  1. Cutoff evaluation (7-day default vs custom cutoff; dry run non-mutating check).
  2. Execute mode disk and DB record deletion.
  3. Active work cancellation.
  4. Cleanup idempotency.
  5. Runnable CLI script execution (`scripts/cleanup.py --dry-run`).
- **`backend/tests/test_security.py`** (8 tests):
  1. Path traversal prevention on filenames and storage keys.
  2. Credential-bearing repository URLs rejection.
  3. Oversized DOCX archives (expansion ratio / zip bombs) and uploads rejection.
  4. Canceled and deleted jobs isolation (404 on deleted resources).
  5. Expired and invalid session handling (401 UNAUTHORIZED).
  6. Structured log redaction verification.
  7. Security response headers & cross-origin request rejection (403).
  8. Actionable error responses without internal server tracebacks.

## Verification
- **All Backend Tests**: 111 passed (`.venv/bin/pytest backend/tests -q`).
- **All Frontend Tests**: 15 passed (`npm test -- --run`).
- **Retention & Security Suites**: 13/13 passed (`pytest -q tests/test_security.py tests/test_retention.py`).
