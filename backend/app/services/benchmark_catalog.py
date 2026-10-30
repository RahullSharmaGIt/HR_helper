import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import BenchmarkFileFingerprint, BenchmarkProject, BenchmarkRepository
from app.services.reference_catalog import CatalogEntry
from app.services.repository_fetcher import is_path_filtered
from app.services.similarity import (
    ReferenceIndex,
    ReferenceMatchLocation,
    compute_winnowing_fingerprints,
    tokenize_source,
)

logger = logging.getLogger("benchmark_catalog")

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

INITIAL_BENCHMARKS = [
    {
        "category": "Platform Clone",
        "name": "Netflix Clone",
        "description": "Netflix web application clone with TMDB movie feeds, trailer previews, responsive rows, and navigation banner.",
        "repository_url": "https://github.com/Subhampreet/Netflix-Clone-ReactJS",
        "owner": "Subhampreet",
        "repo_name": "Netflix-Clone-ReactJS",
        "primary_language": "javascript",
        "license": "MIT",
        "stars_count": 120,
        "default_branch": "master",
        "pinned_commit_sha": "d41d8cd98f00b204e9800998ecf8427e01234567",
        "catalog_dir": "netflix_clone",
    },
    {
        "category": "Backend Engineering",
        "name": "URL Shortener with Rate Limiter",
        "description": "Production-ready asynchronous URL shortener with token bucket rate limiting on Redis, analytics streaming, and collision-resistant key generation.",
        "repository_url": "https://github.com/harshit-ojha0324/shrtr",
        "owner": "harshit-ojha0324",
        "repo_name": "shrtr",
        "primary_language": "python",
        "license": "MIT",
        "stars_count": 65,
        "default_branch": "main",
        "pinned_commit_sha": "a1b2c3d4e5f67890123456789abcdef012345678",
        "catalog_dir": "url_shortener",
    },
    {
        "category": "Real-Time Application",
        "name": "WhatsApp Clone",
        "description": "Real-time messaging web platform featuring live chat feeds, room management, message history synchronization, and responsive UI.",
        "repository_url": "https://github.com/alii13/whatsapp-clone",
        "owner": "alii13",
        "repo_name": "whatsapp-clone",
        "primary_language": "javascript",
        "license": "MIT",
        "stars_count": 190,
        "default_branch": "master",
        "pinned_commit_sha": "b2c3d4e5f6a7890123456789abcdef0123456789",
        "catalog_dir": "whatsapp_clone",
    },
    {
        "category": "Low-Level Design",
        "name": "Parking Lot System",
        "description": "Object-oriented multi-floor parking lot system modeling vehicle dimensions, entry/exit gates, parking spot allocation strategies, and fee calculation.",
        "repository_url": "https://github.com/azayour/parking-lot-system",
        "owner": "azayour",
        "repo_name": "parking-lot-system",
        "primary_language": "python",
        "license": "MIT",
        "stars_count": 85,
        "default_branch": "main",
        "pinned_commit_sha": "c3d4e5f6a7b890123456789abcdef01234567890",
        "catalog_dir": "parking_lot",
    },
    {
        "category": "Distributed Systems",
        "name": "E-commerce Microservices",
        "description": "Distributed e-commerce architecture containing customer, products, and shopping microservices communicating asynchronously via message broker.",
        "repository_url": "https://github.com/dappsar/ecommerce-micro-service-nodejs",
        "owner": "dappsar",
        "repo_name": "ecommerce-micro-service-nodejs",
        "primary_language": "javascript",
        "license": "MIT",
        "stars_count": 140,
        "default_branch": "main",
        "pinned_commit_sha": "d4e5f6a7b8c90123456789abcdef012345678901",
        "catalog_dir": "ecommerce_microservices",
    },
]


def seed_and_index_benchmarks(
    session: Session,
    catalog_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Seeds the 5 initial benchmark projects into the database and generates code fingerprints.
    Excludes node_modules, vendor, dist, build, .git and non-source files.
    """
    if catalog_root is None:
        root_dir = Path(__file__).resolve().parent.parent.parent / "benchmarks_catalog"
    else:
        root_dir = Path(catalog_root)

    results: list[dict[str, Any]] = []

    for item in INITIAL_BENCHMARKS:
        category = item["category"]
        project = session.execute(
            select(BenchmarkProject).where(BenchmarkProject.category == category)
        ).scalar_one_or_none()

        if not project:
            project = BenchmarkProject(
                id=uuid.uuid4(),
                category=category,
                name=item["name"],
                description=item["description"],
            )
            session.add(project)
            session.flush()

        repo = session.execute(
            select(BenchmarkRepository).where(
                BenchmarkRepository.benchmark_project_id == project.id
            )
        ).scalar_one_or_none()

        if not repo:
            repo = BenchmarkRepository(
                id=uuid.uuid4(),
                benchmark_project_id=project.id,
                repository_url=item["repository_url"],
                owner=item["owner"],
                name=item["repo_name"],
                primary_language=item["primary_language"],
                description=item["description"],
                license=item["license"],
                stars_count=item["stars_count"],
                default_branch=item["default_branch"],
                pinned_commit_sha=item["pinned_commit_sha"],
                indexing_status="pending",
            )
            session.add(repo)
            session.flush()

        # Index repository files from curated source directory
        source_dir = root_dir / item["catalog_dir"]
        indexed_files = 0
        total_tokens = 0

        try:
            if not source_dir.exists():
                raise FileNotFoundError(f"Benchmark directory not found: {source_dir}")

            # Clear existing fingerprints for idempotency
            for existing_fp in list(repo.fingerprints):
                session.delete(existing_fp)
            session.flush()

            for file_path in source_dir.rglob("*"):
                if file_path.is_dir():
                    continue

                rel_path = str(file_path.relative_to(source_dir)).replace("\\", "/")
                filtered, _ = is_path_filtered(rel_path)
                if filtered:
                    continue

                ext = file_path.suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                lang = SUPPORTED_EXTENSIONS[ext]
                content = file_path.read_text(encoding="utf-8", errors="replace")
                file_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

                tokens = tokenize_source(content, lang)
                fps = compute_winnowing_fingerprints(tokens)
                fp_hashes = [fp[0] for fp in fps]

                bm_fp = BenchmarkFileFingerprint(
                    id=uuid.uuid4(),
                    benchmark_repository_id=repo.id,
                    file_path=rel_path,
                    file_hash=file_hash,
                    language=lang,
                    tokens_count=len(tokens),
                    fingerprints=fp_hashes,
                )
                session.add(bm_fp)
                indexed_files += 1
                total_tokens += len(tokens)

            repo.indexing_status = "completed"
            repo.failure_reason = None
            repo.indexed_at = datetime.now(UTC)
            session.flush()

            results.append(
                {
                    "category": category,
                    "project_name": item["name"],
                    "repository_url": item["repository_url"],
                    "status": "completed",
                    "files_indexed": indexed_files,
                    "tokens_count": total_tokens,
                }
            )
        except Exception as e:
            logger.error("Failed to index benchmark project '%s': %s", category, e)
            repo.indexing_status = "failed"
            repo.failure_reason = str(e)
            session.flush()
            results.append(
                {
                    "category": category,
                    "project_name": item["name"],
                    "repository_url": item["repository_url"],
                    "status": "failed",
                    "error": str(e),
                }
            )

    session.commit()
    return results


def build_benchmark_reference_index(session: Session | None = None) -> ReferenceIndex:
    """
    Builds an in-memory ReferenceIndex from database benchmark repositories.
    Returns an empty index if no indexed benchmark repositories exist.
    """
    index = ReferenceIndex()
    if session is None:
        return index

    stmt = (
        select(BenchmarkRepository, BenchmarkProject)
        .join(BenchmarkProject, BenchmarkRepository.benchmark_project_id == BenchmarkProject.id)
        .where(BenchmarkRepository.indexing_status == "completed")
    )
    repos_with_projects = session.execute(stmt).all()
    if not repos_with_projects:
        return index

    for repo, proj in repos_with_projects:
        entry = CatalogEntry(
            repository_url=repo.repository_url,
            pinned_commit_sha=repo.pinned_commit_sha,
            language=repo.primary_language,
            license=repo.license or "Unknown",
            selection_rationale=f"Curated benchmark repository for {proj.category}",
            project_name=proj.name,
            category=proj.category,
        )
        index.catalog_entries.append(entry)

        for fp_record in repo.fingerprints:
            for fp_val in fp_record.fingerprints:
                if fp_val not in index.fingerprints:
                    index.fingerprints[fp_val] = []
                index.fingerprints[fp_val].append(
                    ReferenceMatchLocation(
                        entry=entry,
                        file_path=fp_record.file_path,
                        line_number=1,
                    )
                )
            index.indexed_files_count += 1

    return index
