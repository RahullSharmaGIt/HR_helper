import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.services.github_client import normalize_github_repository_url

logger = logging.getLogger("reference_catalog")

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SUPPORTED_LANGUAGES = {"python", "javascript", "typescript"}


@dataclass(frozen=True)
class CatalogEntry:
    repository_url: str
    pinned_commit_sha: str
    language: str
    license: str
    selection_rationale: str
    project_name: str | None = None
    category: str | None = None

    def __post_init__(self):
        # Validate pinned commit SHA
        if not self.pinned_commit_sha or not SHA_PATTERN.match(self.pinned_commit_sha):
            raise ValueError(
                f"Catalog entry '{self.repository_url}' must specify a pinned 40-character commit SHA (got '{self.pinned_commit_sha}')."
            )

        # Validate repository URL
        try:
            canonical_url = normalize_github_repository_url(self.repository_url)
            object.__setattr__(self, "repository_url", canonical_url)
        except Exception as e:
            raise ValueError(f"Invalid repository URL in catalog entry: {e}") from e

        # Validate language
        norm_lang = self.language.lower().strip()
        if norm_lang not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{self.language}'. Supported languages: {sorted(SUPPORTED_LANGUAGES)}"
            )
        object.__setattr__(self, "language", norm_lang)


def load_reference_catalog(catalog_path: str | Path | None = None) -> list[CatalogEntry]:
    """
    Loads and validates reference catalog entries from JSON file.
    Rejects any entries that lack a pinned commit SHA or valid metadata.
    """
    if catalog_path is None:
        catalog_path = Path(__file__).resolve().parent.parent.parent / "reference_catalog.json"
    else:
        catalog_path = Path(catalog_path)

    if not catalog_path.exists():
        logger.warning(
            "Reference catalog file not found at %s. Returning empty catalog.", catalog_path
        )
        return []

    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse reference catalog JSON at {catalog_path}: {e}") from e

    raw_entries = data.get("entries", [])
    catalog_entries: list[CatalogEntry] = []

    for item in raw_entries:
        entry = CatalogEntry(
            repository_url=item.get("repository_url", ""),
            pinned_commit_sha=item.get("pinned_commit_sha", ""),
            language=item.get("language", ""),
            license=item.get("license", "Unknown"),
            selection_rationale=item.get("selection_rationale", ""),
        )
        catalog_entries.append(entry)

    logger.info("Loaded %d validated entries from reference catalog.", len(catalog_entries))
    return catalog_entries
