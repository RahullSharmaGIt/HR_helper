import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas.contracts import EvidenceItem
from app.services.repository_fetcher import RepositoryManifest

logger = logging.getLogger("history_analyzer")

SEP_RECORD = "\x1e"  # ASCII Record Separator
SEP_FIELD = "\x1f"  # ASCII Unit Separator

BOT_PATTERN = re.compile(
    r"(?:\[bot\]|bot@|github-actions|dependabot|renovate|snyk|greenkeeper|semantic-release|codecov)",
    re.IGNORECASE,
)


@dataclass
class ContributorSummary:
    name: str
    redacted_email: str
    commit_count: int
    percentage: float
    is_bot: bool


@dataclass
class CommitRecord:
    sha: str
    parents: list[str]
    author_name: str
    author_email: str
    author_date: str
    committer_name: str
    committer_email: str
    committer_date: str
    subject: str
    is_merge: bool
    changed_files_count: int = 0


@dataclass
class HistoryAnalysisResult:
    total_commits: int
    merge_commits: int
    first_commit_date: str | None
    last_commit_date: str | None
    duration_days: float | None
    contributors: list[ContributorSummary]
    bot_commits_count: int
    alias_match_stats: dict[str, Any] | None
    is_shallow: bool
    is_truncated: bool
    truncation_reasons: list[str] = field(default_factory=list)
    timestamp_anomalies: list[str] = field(default_factory=list)
    has_mailmap: bool = False
    evidence: list[EvidenceItem] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def redact_email(email: str | None) -> str:
    """Redacts contributor email addresses to protect privacy."""
    if not email:
        return "[NO_EMAIL]"
    if "@" not in email:
        return "[REDACTED]"
    user, domain = email.split("@", 1)
    if len(user) <= 2:
        redacted_user = user[0] + "*"
    else:
        redacted_user = user[0] + "*" * (len(user) - 2) + user[-1]
    return f"{redacted_user}@{domain}"


def is_bot(name: str, email: str) -> bool:
    return bool(BOT_PATTERN.search(name) or BOT_PATTERN.search(email))


def _check_mailmap_present(workspace_dir: Path) -> bool:
    res = subprocess.run(
        ["git", "-C", str(workspace_dir), "cat-file", "-e", "HEAD:.mailmap"],
        capture_output=True,
        check=False,
    )
    return res.returncode == 0


def _check_shallow(workspace_dir: Path) -> bool:
    res = subprocess.run(
        ["git", "-C", str(workspace_dir), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        check=False,
    )
    return res.stdout.decode("utf-8").strip() == "true"


def analyze_history(
    repository: RepositoryManifest | str,
    candidate_aliases: list[str] | None = None,
    max_commits: int = 1000,
    runner=None,
) -> HistoryAnalysisResult:
    """
    Summarizes Git history from a bare repository without equating commit counts with authorship.
    Uses machine-safe delimiters, avoids lazy blob fetching, and redacts emails in the report.
    """
    workspace_id = (
        repository.workspace_key if isinstance(repository, RepositoryManifest) else repository
    )
    workspace_dir = Path(settings.storage_dir) / "workspaces" / workspace_id
    if not workspace_dir.exists():
        raise FileNotFoundError(f"Repository workspace '{workspace_id}' not found.")

    run_cmd = runner or subprocess.run
    git_env = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PATH": subprocess.os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin"),
    }

    is_shallow = _check_shallow(workspace_dir)
    has_mailmap = _check_mailmap_present(workspace_dir)

    # Machine-safe git log format: Record Sep (\x1e) and Field Sep (\x1f)
    log_fmt = f"{SEP_RECORD}%H{SEP_FIELD}%P{SEP_FIELD}%an{SEP_FIELD}%ae{SEP_FIELD}%aI{SEP_FIELD}%cn{SEP_FIELD}%ce{SEP_FIELD}%cI{SEP_FIELD}%s"
    cmd = [
        "git",
        "-C",
        str(workspace_dir),
        "log",
        f"--format={log_fmt}",
        "--no-renames",
        "--no-show-signature",
        "-n",
        str(max_commits + 1),  # +1 to detect truncation
    ]

    res = run_cmd(cmd, capture_output=True, env=git_env, check=False)
    if res.returncode != 0:
        # Check if empty repository
        empty_check = run_cmd(
            ["git", "-C", str(workspace_dir), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            env=git_env,
            check=False,
        )
        if empty_check.returncode != 0:
            return HistoryAnalysisResult(
                total_commits=0,
                merge_commits=0,
                first_commit_date=None,
                last_commit_date=None,
                duration_days=0.0,
                contributors=[],
                bot_commits_count=0,
                alias_match_stats=None,
                is_shallow=is_shallow,
                is_truncated=False,
                truncation_reasons=[],
                timestamp_anomalies=[],
                has_mailmap=has_mailmap,
                evidence=[],
                limitations=[
                    "Repository is empty; no commits available to inspect.",
                    "Git history does not prove code authorship.",
                ],
            )
        stderr_text = (res.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"Git log failed: {stderr_text}")

    raw_output = res.stdout.decode("utf-8", errors="replace")
    raw_records = [r for r in raw_output.split(SEP_RECORD) if r.strip()]

    is_truncated = len(raw_records) > max_commits
    truncation_reasons: list[str] = []
    if is_truncated:
        raw_records = raw_records[:max_commits]
        truncation_reasons.append(
            f"Commit traversal bounded at maximum threshold of {max_commits} commits."
        )

    commits: list[CommitRecord] = []
    timestamp_anomalies: list[str] = []
    now_utc = datetime.now(UTC)

    for record in raw_records:
        fields = record.strip().split(SEP_FIELD)
        if len(fields) < 8:
            continue

        sha = fields[0].strip()
        parents = [p for p in fields[1].strip().split() if p]
        author_name = fields[2].strip()
        author_email = fields[3].strip()
        author_date_str = fields[4].strip()
        committer_name = fields[5].strip()
        committer_email = fields[6].strip()
        committer_date_str = fields[7].strip()
        subject = fields[8].strip() if len(fields) > 8 else ""

        is_merge = len(parents) > 1

        # Check timestamp anomalies
        try:
            author_dt = datetime.fromisoformat(author_date_str)
            committer_dt = datetime.fromisoformat(committer_date_str)

            # Future date check
            if author_dt > now_utc:
                timestamp_anomalies.append(
                    f"Commit {sha[:8]} has author date in the future ({author_date_str})."
                )
            # Drift check: committer earlier than author by > 1 hour
            if (author_dt - committer_dt).total_seconds() > 3600:
                timestamp_anomalies.append(
                    f"Commit {sha[:8]} has committer timestamp earlier than author timestamp."
                )
        except ValueError:
            timestamp_anomalies.append(f"Commit {sha[:8]} has invalid ISO timestamp.")

        commits.append(
            CommitRecord(
                sha=sha,
                parents=parents,
                author_name=author_name,
                author_email=author_email,
                author_date=author_date_str,
                committer_name=committer_name,
                committer_email=committer_email,
                committer_date=committer_date_str,
                subject=subject,
                is_merge=is_merge,
            )
        )

    total_commits = len(commits)
    merge_commits = sum(1 for c in commits if c.is_merge)

    # Contributor distribution
    contributor_counts: dict[tuple[str, str], int] = {}
    for c in commits:
        key = (c.author_name, c.author_email)
        contributor_counts[key] = contributor_counts.get(key, 0) + 1

    contributors: list[ContributorSummary] = []
    bot_commits_count = 0

    for (name, email), count in sorted(
        contributor_counts.items(), key=lambda x: x[1], reverse=True
    ):
        bot_flag = is_bot(name, email)
        if bot_flag:
            bot_commits_count += count
        pct = round((count / total_commits) * 100, 1) if total_commits > 0 else 0.0
        contributors.append(
            ContributorSummary(
                name=name,
                redacted_email=redact_email(email),
                commit_count=count,
                percentage=pct,
                is_bot=bot_flag,
            )
        )

    # Date range
    first_commit_date = commits[-1].author_date if commits else None
    last_commit_date = commits[0].author_date if commits else None
    duration_days = None

    if first_commit_date and last_commit_date:
        try:
            start_dt = datetime.fromisoformat(first_commit_date)
            end_dt = datetime.fromisoformat(last_commit_date)
            duration_days = round(abs((end_dt - start_dt).total_seconds()) / 86400, 1)
        except ValueError:
            duration_days = None

    # Optional alias match statistics
    alias_match_stats: dict[str, Any] | None = None
    if candidate_aliases:
        normalized_aliases = {a.lower().strip() for a in candidate_aliases if a.strip()}
        matched_commits = 0
        matching_author_names = set()

        for c in commits:
            name_lower = c.author_name.lower().strip()
            email_lower = c.author_email.lower().strip()
            email_user = email_lower.split("@")[0] if "@" in email_lower else ""

            if (
                name_lower in normalized_aliases
                or email_lower in normalized_aliases
                or email_user in normalized_aliases
            ):
                matched_commits += 1
                matching_author_names.add(c.author_name)

        match_pct = round((matched_commits / total_commits) * 100, 1) if total_commits > 0 else 0.0
        alias_match_stats = {
            "supplied_aliases": list(normalized_aliases),
            "matched_commits_count": matched_commits,
            "matched_percentage": match_pct,
            "matching_contributor_names": list(matching_author_names),
        }

    # Repository URL for evidence linking
    repo_url = repository.repository_url if isinstance(repository, RepositoryManifest) else None

    evidence: list[EvidenceItem] = []
    if commits:
        source_commits = f"{repo_url}/commits" if repo_url else None
        source_earliest = f"{repo_url}/commit/{commits[-1].sha}" if repo_url else None
        source_latest = f"{repo_url}/commit/{commits[0].sha}" if repo_url else None
        evidence.append(
            EvidenceItem(
                id=uuid.uuid4(),
                kind="git_history",
                summary=(
                    f"Analyzed {total_commits} reachable commits spanning "
                    f"{duration_days or 'N/A'} days ({len(contributors)} contributors, {merge_commits} merges)."
                ),
                source_url=source_commits,
                commit_sha=commits[0].sha,
            )
        )
        evidence.append(
            EvidenceItem(
                id=uuid.uuid4(),
                kind="git_history",
                summary=f"Earliest reachable commit: '{commits[-1].subject}' on {first_commit_date}.",
                source_url=source_earliest,
                commit_sha=commits[-1].sha,
            )
        )
        evidence.append(
            EvidenceItem(
                id=uuid.uuid4(),
                kind="git_history",
                summary=f"Latest reachable commit: '{commits[0].subject}' on {last_commit_date}.",
                source_url=source_latest,
                commit_sha=commits[0].sha,
            )
        )

    # Core explicit limitations & disclaimers
    limitations: list[str] = [
        "Git commit logs and author metadata are user-editable and can be easily rewritten or spoofed.",
        "Imported repository history can preserve original author credits from upstream templates or libraries.",
        "Commit frequency or authorship metadata does not prove project understanding or technical competency.",
    ]

    if is_shallow:
        limitations.append(
            "Repository history is shallow; earlier commits are not reachable in this clone."
        )
    if has_mailmap:
        limitations.append(
            "Repository contains a .mailmap file; identity consolidation rules in .mailmap are repository-provided and unverified."
        )
    if candidate_aliases:
        limitations.append(
            "Alias matching is an unverified heuristic based on user input and does not prove identity or authorship."
        )
    if timestamp_anomalies:
        limitations.append(
            f"Detected {len(timestamp_anomalies)} timestamp anomalie(s) in commit history (e.g., date drift, future dates)."
        )

    return HistoryAnalysisResult(
        total_commits=total_commits,
        merge_commits=merge_commits,
        first_commit_date=first_commit_date,
        last_commit_date=last_commit_date,
        duration_days=duration_days,
        contributors=contributors,
        bot_commits_count=bot_commits_count,
        alias_match_stats=alias_match_stats,
        is_shallow=is_shallow,
        is_truncated=is_truncated,
        truncation_reasons=truncation_reasons,
        timestamp_anomalies=timestamp_anomalies,
        has_mailmap=has_mailmap,
        evidence=evidence,
        limitations=limitations,
    )
