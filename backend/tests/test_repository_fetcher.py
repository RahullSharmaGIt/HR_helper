import os
import subprocess
import uuid

import pytest

from app.config import settings
from app.services.repository_fetcher import (
    BlobBudget,
    GitFetchError,
    GitResourceLimitError,
    GitTimeoutError,
    RepositoryManifest,
    fetch_repository,
    read_source_blob,
)


@pytest.fixture
def synthetic_git_repo(tmp_path):
    """Creates a local synthetic Git repository with test files and commits."""
    repo_dir = tmp_path / "origin_repo"
    repo_dir.mkdir()

    env = {
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test Committer",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
    }

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, env=env)

    # 1. Add text file
    (repo_dir / "main.py").write_text("print('hello world')\n")
    # 2. Add binary file
    (repo_dir / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    # 3. Add large file
    (repo_dir / "large.txt").write_text("a" * 1000)

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, env=env)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, env=env)

    return repo_dir


def test_fetch_repository_synthetic_git(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    job_id = uuid.uuid4()

    manifest = fetch_repository(
        str(synthetic_git_repo),
        job_id=job_id,
        allow_file_transport=True,
    )

    assert isinstance(manifest, RepositoryManifest)
    assert manifest.completeness == "full"
    assert len(manifest.analyzed_head_sha) == 40
    assert manifest.pack_size_bytes > 0
    assert (tmp_path / "workspaces" / manifest.workspace_key).exists()


def test_fetch_repository_security_arguments(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    recorded_cmd = None
    recorded_env = None

    def fake_runner(cmd, capture_output=True, env=None, timeout=None, check=False):
        nonlocal recorded_cmd, recorded_env
        recorded_cmd = cmd
        recorded_env = env
        # Return failure to halt after inspecting args
        return subprocess.CompletedProcess(cmd, returncode=1, stderr=b"halt")

    with pytest.raises(GitFetchError):
        fetch_repository(
            "https://github.com/example/safe-repo",
            job_id=uuid.uuid4(),
            runner=fake_runner,
        )

    # Ensure list args, not a shell string
    assert isinstance(recorded_cmd, list)
    assert "--bare" in recorded_cmd
    assert "--filter=blob:none" in recorded_cmd
    assert "-c" in recorded_cmd
    assert "core.hooksPath=/dev/null" in recorded_cmd
    assert "credential.helper=" in recorded_cmd

    # Ensure isolated environment variables
    assert recorded_env["GIT_TERMINAL_PROMPT"] == "0"
    assert recorded_env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert recorded_env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert recorded_env["GIT_ALLOW_PROTOCOL"] == "https"


def test_fetch_repository_rejects_malicious_urls():
    with pytest.raises(ValueError, match="Embedded credentials"):
        fetch_repository("https://user:pass@github.com/alice/repo", job_id=uuid.uuid4())

    with pytest.raises(ValueError, match="Only public github.com repositories"):
        fetch_repository("https://gitlab.com/alice/repo", job_id=uuid.uuid4())


def test_fetch_repository_timeout_handling(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    def fake_runner_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=0.1)

    with pytest.raises(GitTimeoutError, match="timed out"):
        fetch_repository(
            "https://github.com/example/repo",
            job_id=uuid.uuid4(),
            runner=fake_runner_timeout,
        )


def test_fetch_repository_pack_size_limit(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "git_max_pack_size_bytes", 5)  # Intentionally tiny limit

    with pytest.raises(GitResourceLimitError, match="pack size"):
        fetch_repository(
            str(synthetic_git_repo),
            job_id=uuid.uuid4(),
            allow_file_transport=True,
        )


def test_read_source_blob_success(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    manifest = fetch_repository(
        str(synthetic_git_repo),
        job_id=uuid.uuid4(),
        allow_file_transport=True,
    )

    result = read_source_blob(manifest, manifest.analyzed_head_sha, "main.py")
    assert result.skipped is False
    assert result.content == "print('hello world')\n"
    assert result.is_binary is False
    assert result.byte_size > 0


def test_read_source_blob_skips_binary_content(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    manifest = fetch_repository(
        str(synthetic_git_repo),
        job_id=uuid.uuid4(),
        allow_file_transport=True,
    )

    # image.bin contains null bytes and binary extension
    result = read_source_blob(manifest, manifest.analyzed_head_sha, "image.bin")
    assert result.skipped is True
    assert "Binary" in (result.skip_reason or "")


def test_read_source_blob_skips_vendor_and_generated(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    manifest = fetch_repository(
        str(synthetic_git_repo),
        job_id=uuid.uuid4(),
        allow_file_transport=True,
    )

    res_vendor = read_source_blob(manifest, manifest.analyzed_head_sha, "node_modules/lib.js")
    assert res_vendor.skipped is True
    assert "Vendor" in (res_vendor.skip_reason or "")

    res_lock = read_source_blob(manifest, manifest.analyzed_head_sha, "package-lock.json")
    assert res_lock.skipped is True
    assert "Generated" in (res_lock.skip_reason or "")


def test_read_source_blob_skips_oversized_file(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "git_max_blob_size_bytes", 50)  # 50 bytes limit

    manifest = fetch_repository(
        str(synthetic_git_repo),
        job_id=uuid.uuid4(),
        allow_file_transport=True,
    )

    result = read_source_blob(manifest, manifest.analyzed_head_sha, "large.txt")
    assert result.skipped is True
    assert "exceeds" in (result.skip_reason or "")


def test_read_source_blob_budget_exhaustion(synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    manifest = fetch_repository(
        str(synthetic_git_repo),
        job_id=uuid.uuid4(),
        allow_file_transport=True,
    )

    budget = BlobBudget(max_files=1, max_total_bytes=10000)

    # First read uses budget slot
    res1 = read_source_blob(manifest, manifest.analyzed_head_sha, "main.py", budget=budget)
    assert res1.skipped is False

    # Second read exceeds file budget
    res2 = read_source_blob(manifest, manifest.analyzed_head_sha, "large.txt", budget=budget)
    assert res2.skipped is True
    assert "budget exceeded" in (res2.skip_reason or "")
