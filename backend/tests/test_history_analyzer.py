import os
import subprocess
import uuid

import pytest

from app.config import settings
from app.services.history_analyzer import analyze_history, is_bot, redact_email
from app.services.repository_fetcher import fetch_repository


def test_redact_email():
    assert redact_email("alice@example.com") == "a***e@example.com"
    assert redact_email("bo@example.com") == "b*@example.com"
    assert redact_email("developer@domain.org") == "d*******r@domain.org"
    assert redact_email("") == "[NO_EMAIL]"
    assert redact_email(None) == "[NO_EMAIL]"
    assert redact_email("invalid-email") == "[REDACTED]"


def test_is_bot():
    assert is_bot("dependabot[bot]", "dependabot@github.com") is True
    assert is_bot("github-actions[bot]", "actions@github.com") is True
    assert is_bot("Alice", "bot@service.com") is True
    assert is_bot("Alice Developer", "alice@example.com") is False


@pytest.fixture
def complex_synthetic_git_repo(tmp_path):
    repo_dir = tmp_path / "complex_repo"
    repo_dir.mkdir()

    def git_commit(
        msg: str,
        author_name: str,
        author_email: str,
        author_date: str,
        committer_date: str | None = None,
    ):
        c_date = committer_date or author_date
        env = {
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_AUTHOR_DATE": author_date,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
            "GIT_COMMITTER_DATE": c_date,
            "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
        }
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True, env=env)

    # 1. Initialize repo
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)

    # Commit 1: Alice
    (repo_dir / "file1.txt").write_text("initial")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    git_commit("Initial commit", "Alice Dev", "alice@example.com", "2024-01-01T10:00:00Z")

    # Commit 2: Bob
    (repo_dir / "file2.txt").write_text("bob contribution")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    git_commit("Bob feature", "Bob Builder", "bob@example.com", "2024-01-03T12:00:00Z")

    # Commit 3: Bot
    (repo_dir / "package.json").write_text('{"name": "test"}')
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    git_commit(
        "Bump dependencies", "dependabot[bot]", "dependabot@github.com", "2024-01-05T09:00:00Z"
    )

    # Commit 4: Feature branch by Alice
    subprocess.run(["git", "checkout", "-b", "feature-x"], cwd=repo_dir, check=True)
    (repo_dir / "feature.txt").write_text("feature content")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    git_commit("Feature branch work", "Alice Dev", "alice@example.com", "2024-01-06T14:00:00Z")

    # Merge into main
    subprocess.run(["git", "checkout", "main"], cwd=repo_dir, check=True)
    env = {
        "GIT_AUTHOR_NAME": "Alice Dev",
        "GIT_AUTHOR_EMAIL": "alice@example.com",
        "GIT_AUTHOR_DATE": "2024-01-07T10:00:00Z",
        "GIT_COMMITTER_NAME": "Alice Dev",
        "GIT_COMMITTER_EMAIL": "alice@example.com",
        "GIT_COMMITTER_DATE": "2024-01-07T10:00:00Z",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
    }
    subprocess.run(
        ["git", "merge", "--no-ff", "feature-x", "-m", "Merge feature-x"],
        cwd=repo_dir,
        check=True,
        env=env,
    )

    # Commit 5: Anomaly (Committer date earlier than author date by 2 days)
    (repo_dir / "anomaly.txt").write_text("skewed timestamps")
    (repo_dir / ".mailmap").write_text(
        "Alice Dev <alice@example.com> Alice Developer <alice@corp.com>\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    git_commit(
        "Timestamp drift commit",
        "Alice Dev",
        "alice@example.com",
        author_date="2024-01-10T12:00:00Z",
        committer_date="2024-01-08T12:00:00Z",
    )

    return repo_dir


def test_analyze_history_comprehensive(complex_synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    job_id = uuid.uuid4()

    # Clone bare repo
    manifest = fetch_repository(
        str(complex_synthetic_git_repo),
        job_id=job_id,
        allow_file_transport=True,
    )
    manifest.repository_url = "https://github.com/example-org/complex-repo"

    # Analyze history
    result = analyze_history(
        manifest,
        candidate_aliases=["alice", "alice@example.com"],
    )

    # 1. Total commits and merges
    assert result.total_commits == 6
    assert result.merge_commits == 1

    # 2. Date range
    assert result.first_commit_date == "2024-01-01T10:00:00Z"
    assert result.duration_days is not None
    assert result.duration_days > 8.0

    # 3. Contributors & redaction
    assert len(result.contributors) >= 3
    alice_contrib = next(c for c in result.contributors if c.name == "Alice Dev")
    assert alice_contrib.redacted_email == "a***e@example.com"
    assert "alice@example.com" not in [c.redacted_email for c in result.contributors]

    # 4. Bot identification
    assert result.bot_commits_count == 1
    bot_contrib = next(c for c in result.contributors if "dependabot" in c.name)
    assert bot_contrib.is_bot is True

    # 5. Alias matching stats
    assert result.alias_match_stats is not None
    assert result.alias_match_stats["matched_commits_count"] == 4
    assert result.alias_match_stats["matched_percentage"] > 60.0

    # 6. Mailmap detection & disclaimer
    assert result.has_mailmap is True
    assert any(".mailmap" in lim for lim in result.limitations)

    # 7. Timestamp anomaly detection
    assert len(result.timestamp_anomalies) >= 1
    assert any("earlier than author" in a for a in result.timestamp_anomalies)

    # 8. Evidence items contain GitHub commit links
    assert len(result.evidence) >= 3
    for ev in result.evidence:
        assert ev.source_url.startswith("https://github.com/example-org/complex-repo")

    # 9. Authorship disclaimers present
    assert any("does not prove" in lim for lim in result.limitations)
    assert any("can be easily rewritten" in lim for lim in result.limitations)


def test_analyze_history_empty_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=empty_repo, check=True)

    # Manifest pointing to empty repo
    workspace_dir = tmp_path / "workspaces" / "job_empty"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare"], cwd=workspace_dir, check=True)

    result = analyze_history("job_empty")
    assert result.total_commits == 0
    assert result.merge_commits == 0
    assert result.contributors == []
    assert any("empty" in lim for lim in result.limitations)


def test_analyze_history_traversal_truncation(complex_synthetic_git_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    manifest = fetch_repository(
        str(complex_synthetic_git_repo),
        job_id=uuid.uuid4(),
        allow_file_transport=True,
    )

    # Bound traversal to max 2 commits
    result = analyze_history(manifest, max_commits=2)
    assert result.is_truncated is True
    assert len(result.truncation_reasons) == 1
    assert "bounded at maximum threshold of 2" in result.truncation_reasons[0].lower()
    assert result.total_commits == 2
