from app.services.github_client import (
    GitHubClient,
    GitHubError,
    GitHubRateLimitError,
    GitHubRepoNotFoundError,
    GitHubTransientError,
    normalize_github_repository_url,
)
from app.services.history_analyzer import (
    ContributorSummary,
    HistoryAnalysisResult,
    analyze_history,
    redact_email,
)
from app.services.job_service import (
    JobServiceError,
    cancel_analysis,
    enqueue_analysis,
)
from app.services.project_extraction import extract_github_urls, extract_project_suggestions
from app.services.reference_catalog import CatalogEntry, load_reference_catalog
from app.services.repository_discovery import discover_repositories
from app.services.repository_fetcher import (
    BlobBudget,
    GitFetchError,
    GitResourceLimitError,
    GitTimeoutError,
    RepositoryManifest,
    SourceBlobResult,
    fetch_repository,
    read_source_blob,
)
from app.services.resumes import (
    PageContent,
    ResumeExtractionResult,
    extract_resume_text,
    store_resume,
    validate_batch_size,
    validate_resume,
)
from app.services.scoring import (
    COVERAGE_WEIGHTS,
    AssessmentResult,
    CoverageComponent,
    Observation,
    build_assessment,
)
from app.services.similarity import (
    PathMatchDetail,
    ReferenceIndex,
    SimilarityAnalysisResult,
    build_reference_index,
    compare_repository,
    compute_winnowing_fingerprints,
    tokenize_source,
)

__all__ = [
    "COVERAGE_WEIGHTS",
    "AssessmentResult",
    "BlobBudget",
    "CatalogEntry",
    "ContributorSummary",
    "CoverageComponent",
    "GitFetchError",
    "GitHubClient",
    "GitHubError",
    "GitHubRateLimitError",
    "GitHubRepoNotFoundError",
    "GitHubTransientError",
    "GitResourceLimitError",
    "GitTimeoutError",
    "HistoryAnalysisResult",
    "JobServiceError",
    "Observation",
    "PageContent",
    "PathMatchDetail",
    "ReferenceIndex",
    "RepositoryManifest",
    "ResumeExtractionResult",
    "SimilarityAnalysisResult",
    "SourceBlobResult",
    "analyze_history",
    "build_assessment",
    "build_reference_index",
    "cancel_analysis",
    "compare_repository",
    "compute_winnowing_fingerprints",
    "discover_repositories",
    "enqueue_analysis",
    "extract_github_urls",
    "extract_project_suggestions",
    "extract_resume_text",
    "fetch_repository",
    "load_reference_catalog",
    "normalize_github_repository_url",
    "read_source_blob",
    "redact_email",
    "store_resume",
    "tokenize_source",
    "validate_batch_size",
    "validate_resume",
]
