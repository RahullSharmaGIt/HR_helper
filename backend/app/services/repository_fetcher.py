import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.services.github_client import normalize_github_repository_url

logger = logging.getLogger("repository_fetcher")

# Concurrency limiter
_CLONE_SEMAPHORE = threading.BoundedSemaphore(settings.git_max_concurrent_clones)

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pyc",
    ".class",
    ".jar",
    ".o",
    ".a",
}

VENDOR_DIR_PATTERNS = [
    re.compile(r"(^|/)(?:node_modules|vendor|\.venv|env|dist|build|\.git)(/|$)"),
]

GENERATED_FILE_PATTERNS = [
    re.compile(r"\.(?:min\.js|bundle\.js|min\.css|map)$"),
    re.compile(r"(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Cargo\.lock|poetry\.lock)$"),
]


class GitFetchError(Exception):
    """Base exception for Git repository fetch errors."""


class GitResourceLimitError(GitFetchError):
    """Raised when repository disk consumption or pack size exceeds limits."""


class GitTimeoutError(GitFetchError):
    """Raised when git subprocess duration bounds are violated."""


@dataclass
class RepositoryManifest:
    workspace_key: str
    repository_url: str
    analyzed_head_sha: str
    fetch_time_seconds: float
    completeness: str  # "full", "truncated", "partial"
    truncation_reasons: list[str] = field(default_factory=list)
    pack_size_bytes: int = 0


@dataclass
class SourceBlobResult:
    path: str
    commit_sha: str
    content: str | None = None
    skipped: bool = False
    skip_reason: str | None = None
    byte_size: int = 0
    is_binary: bool = False


@dataclass
class BlobBudget:
    max_files: int = settings.git_max_blobs_per_job
    max_total_bytes: int = settings.git_max_total_blob_bytes
    files_read: int = 0
    bytes_read: int = 0

    def can_read(self, size: int) -> bool:
        return (self.files_read < self.max_files) and (
            self.bytes_read + size <= self.max_total_bytes
        )

    def record(self, size: int) -> None:
        self.files_read += 1
        self.bytes_read += size


def _get_directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def is_path_filtered(path: str) -> tuple[bool, str | None]:
    norm_path = path.replace("\\", "/").strip("/")

    # 1. Extension check
    _, ext = os.path.splitext(norm_path)
    if ext.lower() in BINARY_EXTENSIONS:
        return True, f"Binary file extension: {ext}"

    # 2. Vendor directory patterns
    for pat in VENDOR_DIR_PATTERNS:
        if pat.search(norm_path):
            return True, f"Vendor/dependency path pattern: {norm_path}"

    # 3. Generated file patterns
    for pat in GENERATED_FILE_PATTERNS:
        if pat.search(norm_path):
            return True, f"Generated or lockfile artifact: {norm_path}"

    return False, None


def fetch_repository(
    repository_url: str,
    job_id: uuid.UUID | str,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    allow_file_transport: bool = False,
) -> RepositoryManifest:
    """
    Safely clones a public repository's history using git clone --bare --filter=blob:none.
    Enforces subprocess duration, disk consumption, output bounds, and strict isolation.
    """
    # Deterministic test adapter mode
    if settings.allow_test_adapters:
        if "inaccessible" in repository_url:
            raise GitFetchError("Remote repository not found or inaccessible.")
        if "portfolio-app" in repository_url:
            fixture_repo = Path(__file__).resolve().parent.parent.parent / "tests/fixtures/synthetic_repos/portfolio-app.git"
            if fixture_repo.exists():
                repository_url = str(fixture_repo)
                allow_file_transport = True

    # 1. Validate public GitHub URL (unless explicitly test-overridden)
    if not allow_file_transport:
        canonical_url = normalize_github_repository_url(repository_url)
    else:
        canonical_url = repository_url

    run_cmd = runner or subprocess.run
    start_time = time.monotonic()

    # 2. Create isolated workspace directory
    workspace_id = f"job_{job_id}_{uuid.uuid4().hex[:8]}"
    workspace_dir = Path(settings.storage_dir) / "workspaces" / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)

    git_env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ALLOW_PROTOCOL": "file:https" if allow_file_transport else "https",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
    }

    cmd = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "-c",
        "advice.detachedHead=false",
        "clone",
        "--bare",
        "--filter=blob:none",
        "--single-branch",
        canonical_url,
        str(workspace_dir),
    ]

    acquired = _CLONE_SEMAPHORE.acquire(timeout=settings.git_clone_timeout_seconds)
    if not acquired:
        shutil.rmtree(workspace_dir, ignore_errors=True)
        raise GitTimeoutError("Timed out waiting for available clone worker slot.")

    try:
        try:
            res = run_cmd(
                cmd,
                capture_output=True,
                env=git_env,
                timeout=settings.git_clone_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise GitTimeoutError(
                f"Repository fetch timed out after {settings.git_clone_timeout_seconds}s"
            ) from e

        if res.returncode != 0:
            shutil.rmtree(workspace_dir, ignore_errors=True)
            stderr_preview = (res.stderr or b"")[:500].decode("utf-8", errors="replace")
            raise GitFetchError(f"Git clone failed (exit code {res.returncode}): {stderr_preview}")

        # 3. Check disk consumption / pack size
        pack_size = _get_directory_size(workspace_dir)
        if pack_size > settings.git_max_pack_size_bytes:
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise GitResourceLimitError(
                f"Repository pack size ({pack_size} bytes) exceeded maximum limit of {settings.git_max_pack_size_bytes} bytes."
            )

        # 4. Read analyzed HEAD SHA
        head_cmd = ["git", "-C", str(workspace_dir), "rev-parse", "HEAD"]
        head_res = run_cmd(
            head_cmd,
            capture_output=True,
            env=git_env,
            timeout=5.0,
            check=False,
        )
        if head_res.returncode != 0:
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise GitFetchError("Failed to resolve HEAD commit SHA.")

        head_sha = head_res.stdout.decode("utf-8").strip()
        if not re.match(r"^[0-9a-f]{40}$", head_sha):
            shutil.rmtree(workspace_dir, ignore_errors=True)
            raise GitFetchError(f"Invalid HEAD SHA format: {head_sha}")

        fetch_duration = round(time.monotonic() - start_time, 3)

        return RepositoryManifest(
            workspace_key=workspace_id,
            repository_url=canonical_url,
            analyzed_head_sha=head_sha,
            fetch_time_seconds=fetch_duration,
            completeness="full",
            truncation_reasons=[],
            pack_size_bytes=pack_size,
        )

    finally:
        _CLONE_SEMAPHORE.release()


def read_source_blob(
    repository: RepositoryManifest | str,
    commit_sha: str,
    path: str,
    budget: BlobBudget | None = None,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
) -> SourceBlobResult:
    """
    Retrieves an individual source blob lazily without checking out a full working tree.
    Enforces per-file byte limit, cumulative budget, timeout, and skips binary/vendor/generated files.
    """
    workspace_id = (
        repository.workspace_key if isinstance(repository, RepositoryManifest) else repository
    )
    workspace_dir = Path(settings.storage_dir) / "workspaces" / workspace_id
    if not workspace_dir.exists():
        raise FileNotFoundError(f"Repository workspace '{workspace_id}' not found.")

    run_cmd = runner or subprocess.run

    # 1. Inspect path filtering (vendor, generated, binary extensions)
    filtered, reason = is_path_filtered(path)
    if filtered:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason=reason,
        )

    git_env = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
    }

    # 2. Check object size first via git cat-file -s
    size_cmd = ["git", "-C", str(workspace_dir), "cat-file", "-s", f"{commit_sha}:{path}"]
    try:
        size_res = run_cmd(
            size_cmd,
            capture_output=True,
            env=git_env,
            timeout=settings.git_blob_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason="Subprocess timeout inspecting file size",
        )

    if size_res.returncode != 0:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason=f"Path not found in commit {commit_sha}",
        )

    try:
        file_size = int(size_res.stdout.decode("utf-8").strip())
    except ValueError:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason="Failed to parse object size",
        )

    # 3. Check file byte limit
    if file_size > settings.git_max_blob_size_bytes:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason=f"File size ({file_size} bytes) exceeds {settings.git_max_blob_size_bytes} limit",
            byte_size=file_size,
        )

    # 4. Check cumulative budget
    if budget is not None and not budget.can_read(file_size):
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason="Cumulative blob extraction budget exceeded",
            byte_size=file_size,
        )

    # 5. Fetch blob content via git cat-file -p
    blob_cmd = ["git", "-C", str(workspace_dir), "cat-file", "-p", f"{commit_sha}:{path}"]
    try:
        blob_res = run_cmd(
            blob_cmd,
            capture_output=True,
            env=git_env,
            timeout=settings.git_blob_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason="Subprocess timeout reading blob",
            byte_size=file_size,
        )

    if blob_res.returncode != 0:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason="Failed to read object content from repository",
            byte_size=file_size,
        )

    raw_bytes = blob_res.stdout
    # 6. Binary detection (null byte in first 1024 bytes)
    if b"\x00" in raw_bytes[:1024]:
        return SourceBlobResult(
            path=path,
            commit_sha=commit_sha,
            skipped=True,
            skip_reason="Binary content detected",
            byte_size=file_size,
            is_binary=True,
        )

    content_str = raw_bytes.decode("utf-8", errors="replace")
    if budget is not None:
        budget.record(file_size)

    return SourceBlobResult(
        path=path,
        commit_sha=commit_sha,
        content=content_str,
        skipped=False,
        byte_size=file_size,
        is_binary=False,
    )
