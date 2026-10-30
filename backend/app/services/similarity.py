import hashlib
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.schemas.contracts import EvidenceItem, Measurement
from app.services.reference_catalog import CatalogEntry
from app.services.repository_fetcher import RepositoryManifest, is_path_filtered, read_source_blob

logger = logging.getLogger("similarity")

ALGORITHM_VERSION = "winnowing-v1.0"
DEFAULT_K_SHINGLE = 12
DEFAULT_WINDOW_SIZE = 6

PYTHON_KEYWORDS = {
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
}

JS_TS_KEYWORDS = {
    "abstract",
    "any",
    "as",
    "async",
    "await",
    "boolean",
    "break",
    "case",
    "catch",
    "class",
    "const",
    "continue",
    "debugger",
    "default",
    "delete",
    "do",
    "else",
    "enum",
    "export",
    "extends",
    "false",
    "finally",
    "for",
    "from",
    "function",
    "if",
    "implements",
    "import",
    "in",
    "instanceof",
    "interface",
    "let",
    "new",
    "null",
    "number",
    "of",
    "private",
    "protected",
    "public",
    "return",
    "string",
    "super",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "type",
    "typeof",
    "undefined",
    "var",
    "void",
    "while",
    "with",
    "yield",
}


@dataclass
class ReferenceMatchLocation:
    entry: CatalogEntry
    file_path: str
    line_number: int


@dataclass
class ReferenceIndex:
    fingerprints: dict[int, list[ReferenceMatchLocation]] = field(default_factory=dict)
    indexed_files_count: int = 0
    catalog_entries: list[CatalogEntry] = field(default_factory=list)

    def is_empty(self) -> bool:
        return len(self.fingerprints) == 0

    def add_reference_file(self, entry: CatalogEntry, file_path: str, content: str) -> None:
        tokens = tokenize_source(content, entry.language)
        fps = compute_winnowing_fingerprints(tokens)
        for fp, line_num in fps:
            if fp not in self.fingerprints:
                self.fingerprints[fp] = []
            self.fingerprints[fp].append(
                ReferenceMatchLocation(entry=entry, file_path=file_path, line_number=line_num)
            )
        self.indexed_files_count += 1
        if entry not in self.catalog_entries:
            self.catalog_entries.append(entry)


@dataclass
class PathMatchDetail:
    candidate_path: str
    reference_url: str
    reference_commit_sha: str
    reference_path: str
    matched_fingerprints: int
    total_candidate_fingerprints: int
    overlap_ratio: float
    benchmark_project_name: str | None = None
    benchmark_category: str | None = None


@dataclass
class SimilarityAnalysisResult:
    overlap_score: Measurement[float]
    matched_paths: list[PathMatchDetail]
    reference_commit_links: list[str]
    coverage_statistics: dict[str, Any]
    algorithm_version: str
    algorithm_configuration: dict[str, Any]
    evidence: list[EvidenceItem]
    limitations: list[str]


def tokenize_source(code: str, language: str) -> list[tuple[str, int]]:
    """
    Normalizes source code into a stream of (token_value, line_number) tuples.
    Normalizes variable/function identifiers to '_ID_' to enable detection of renamed identifiers.
    """
    lang = language.lower()
    keywords = PYTHON_KEYWORDS if lang == "python" else JS_TS_KEYWORDS

    # 1. Strip comments
    lines = code.splitlines()
    tokens_with_lines: list[tuple[str, int]] = []

    # Pattern for string literals, numbers, identifiers, operators
    token_pattern = re.compile(
        r"""
        (?P<STR>'(?:\\.|[^'])*'|"(?:\\.|[^"])*")|
        (?P<NUM>\b\d+(?:\.\d+)?\b)|
        (?P<ID>\b[A-Za-z_][A-Za-z0-9_]*\b)|
        (?P<OP>[+\-*/%&|^=<>!]=?|[(){}\[\],;:.])
    """,
        re.VERBOSE,
    )

    in_block_comment = False

    for line_idx, raw_line in enumerate(lines, start=1):
        line = raw_line

        # Block comment handling for JS/TS
        if lang in {"javascript", "typescript"}:
            if in_block_comment:
                end_pos = line.find("*/")
                if end_pos != -1:
                    line = line[end_pos + 2 :]
                    in_block_comment = False
                else:
                    continue

            # Strip full block comments on same line
            line = re.sub(r"/\*.*?\*/", " ", line)

            # Check open block comment
            start_pos = line.find("/*")
            if start_pos != -1:
                line = line[:start_pos]
                in_block_comment = True

            # Strip line comments
            line = re.sub(r"//.*$", "", line)

        elif lang == "python":
            # Strip line comments
            line = re.sub(r"#.*$", "", line)

        for match in token_pattern.finditer(line):
            kind = match.lastgroup
            val = match.group(kind)
            if kind == "STR":
                tokens_with_lines.append(("_STR_", line_idx))
            elif kind == "NUM":
                tokens_with_lines.append(("_NUM_", line_idx))
            elif kind == "ID":
                if val.lower() in keywords:
                    tokens_with_lines.append((val.lower(), line_idx))
                else:
                    tokens_with_lines.append(("_ID_", line_idx))
            elif kind == "OP":
                tokens_with_lines.append((val, line_idx))

    return tokens_with_lines


def compute_winnowing_fingerprints(
    tokens: list[tuple[str, int]],
    k: int = DEFAULT_K_SHINGLE,
    w: int = DEFAULT_WINDOW_SIZE,
) -> list[tuple[int, int]]:
    """
    Computes winnowing fingerprints using deterministic hash over k-shingles.
    Returns list of (fingerprint_hash, line_number) tuples.
    """
    if len(tokens) < k:
        return []

    # 1. Compute k-shingle hashes
    shingle_hashes: list[tuple[int, int]] = []
    for i in range(len(tokens) - k + 1):
        shingle_tokens = tuple(t[0] for t in tokens[i : i + k])
        line_num = tokens[i][1]

        # Deterministic 64-bit integer hash using MD5
        digest = hashlib.md5(" ".join(shingle_tokens).encode("utf-8")).digest()
        hash_val = int.from_bytes(digest[:8], byteorder="big")
        shingle_hashes.append((hash_val, line_num))

    # 2. Sliding window of size w over hashes (Winnowing)
    if len(shingle_hashes) < w:
        min_elem = min(shingle_hashes, key=lambda x: x[0])
        return [min_elem]

    fingerprints: list[tuple[int, int]] = []
    min_idx = -1

    for i in range(len(shingle_hashes) - w + 1):
        window = shingle_hashes[i : i + w]
        # Pick rightmost minimum in window
        window_min = min(window, key=lambda x: x[0])
        current_min_idx = i + [item[0] for item in window].index(window_min[0])

        if current_min_idx != min_idx:
            min_idx = current_min_idx
            fingerprints.append(window_min)

    return fingerprints


def build_reference_index(catalog: list[CatalogEntry]) -> ReferenceIndex:
    """
    Builds in-memory winnowing fingerprint index for the provided reference catalog entries.
    """
    index = ReferenceIndex(catalog_entries=list(catalog))
    return index


def _get_candidate_repo_files(workspace_dir: Path, head_sha: str) -> list[str]:
    """Lists files in the candidate bare repository using git ls-tree."""
    cmd = ["git", "-C", str(workspace_dir), "ls-tree", "-r", "--name-only", head_sha]
    res = subprocess.run(cmd, capture_output=True, check=False)
    if res.returncode != 0:
        return []
    paths = res.stdout.decode("utf-8", errors="replace").splitlines()
    return [p.strip() for p in paths if p.strip()]


def compare_repository(
    repository: RepositoryManifest | str,
    reference_index: ReferenceIndex,
    runner=None,
) -> SimilarityAnalysisResult:
    """
    Compares candidate repository source files against the reference fingerprint index.
    Produces evidence of shared syntactic structure without asserting borrowing direction or misconduct.
    Empty references or unreadable source yield an explicit unavailable result.
    """
    algo_config = {
        "k_shingle_size": DEFAULT_K_SHINGLE,
        "window_size": DEFAULT_WINDOW_SIZE,
        "supported_languages": ["python", "javascript", "typescript"],
    }

    # 1. Resolve candidate repository
    if isinstance(repository, RepositoryManifest):
        workspace_id = repository.workspace_key
        head_sha = repository.analyzed_head_sha
    else:
        workspace_id = repository
        head_sha = "HEAD"

    workspace_dir = Path(settings.storage_dir) / "workspaces" / workspace_id
    if not workspace_dir.exists():
        raise FileNotFoundError(f"Candidate repository workspace '{workspace_id}' not found.")

    all_files = _get_candidate_repo_files(workspace_dir, head_sha)
    analyzable_extensions = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }

    candidate_files = []
    for f in all_files:
        filtered, _ = is_path_filtered(f)
        if filtered:
            continue
        ext = Path(f).suffix.lower()
        if ext in analyzable_extensions:
            candidate_files.append((f, analyzable_extensions[ext]))

    # Bound candidate files (max 50 files)
    candidate_files = candidate_files[:50]

    # Pre-parse candidate files to compute inspectable tokens and file counts
    candidate_file_blobs: list[tuple[str, str, list[tuple[str, int]]]] = []
    total_tokens_count = 0
    for file_path, lang in candidate_files:
        blob_result = read_source_blob(workspace_id, head_sha, file_path, runner=runner)
        if blob_result.skipped or not blob_result.content:
            continue
        tokens = tokenize_source(blob_result.content, lang)
        total_tokens_count += len(tokens)
        candidate_file_blobs.append((file_path, lang, tokens))

    candidate_files_count = len(candidate_file_blobs)

    # 2. Handle empty reference index
    if reference_index.is_empty():
        return SimilarityAnalysisResult(
            overlap_score=Measurement[float](
                value=None,
                reason="Reference catalog collection is empty; similarity measurement unavailable.",
            ),
            matched_paths=[],
            reference_commit_links=[],
            coverage_statistics={
                "candidate_files_analyzed": candidate_files_count,
                "candidate_tokens_analyzed": total_tokens_count,
                "reference_files_indexed": 0,
            },
            algorithm_version=ALGORITHM_VERSION,
            algorithm_configuration=algo_config,
            evidence=[],
            limitations=[
                "Reference catalog is empty; comparisons cannot be conducted.",
                "Similarity results only evaluate matches against the configured reference collection.",
            ],
        )

    if not candidate_files:
        return SimilarityAnalysisResult(
            overlap_score=Measurement[float](
                value=None,
                reason="No analyzable Python or JavaScript/TypeScript source files found in candidate repository.",
            ),
            matched_paths=[],
            reference_commit_links=[],
            coverage_statistics={
                "candidate_files_analyzed": 0,
                "candidate_tokens_analyzed": 0,
                "reference_files_indexed": reference_index.indexed_files_count,
            },
            algorithm_version=ALGORITHM_VERSION,
            algorithm_configuration=algo_config,
            evidence=[],
            limitations=[
                "Candidate repository contains no readable source files in supported languages.",
                "Similarity measurements are restricted to Python, JavaScript, and TypeScript.",
            ],
        )

    total_candidate_fps = 0
    matched_candidate_fps = 0
    matched_paths_details: list[PathMatchDetail] = []
    matched_commit_urls: set[str] = set()

    for file_path, lang, tokens in candidate_file_blobs:
        fps = compute_winnowing_fingerprints(tokens)
        if not fps:
            continue

        total_candidate_fps += len(fps)
        file_matches = 0

        # Group matches by reference entry
        best_ref_match: ReferenceMatchLocation | None = None

        for fp, _ in fps:
            if fp in reference_index.fingerprints:
                file_matches += 1
                matched_candidate_fps += 1
                locs = reference_index.fingerprints[fp]
                if locs and not best_ref_match:
                    best_ref_match = locs[0]

        if file_matches > 0 and best_ref_match:
            ref_entry = best_ref_match.entry
            ratio = round(file_matches / len(fps), 3)
            matched_paths_details.append(
                PathMatchDetail(
                    candidate_path=file_path,
                    reference_url=ref_entry.repository_url,
                    reference_commit_sha=ref_entry.pinned_commit_sha,
                    reference_path=best_ref_match.file_path,
                    matched_fingerprints=file_matches,
                    total_candidate_fingerprints=len(fps),
                    overlap_ratio=ratio,
                    benchmark_project_name=ref_entry.project_name,
                    benchmark_category=ref_entry.category,
                )
            )
            commit_link = f"{ref_entry.repository_url}/commit/{ref_entry.pinned_commit_sha}"
            matched_commit_urls.add(commit_link)

    overall_overlap_pct = (
        round((matched_candidate_fps / total_candidate_fps) * 100, 1)
        if total_candidate_fps > 0
        else 0.0
    )

    evidence_items: list[EvidenceItem] = []
    for detail in matched_paths_details[:5]:
        evidence_items.append(
            EvidenceItem(
                id=uuid.uuid4(),
                kind="similarity",
                summary=(
                    f"Candidate file '{detail.candidate_path}' shares syntactic winnowing fingerprints "
                    f"({int(detail.overlap_ratio * 100)}% match) with reference '{detail.reference_path}' "
                    f"from {detail.reference_url}."
                ),
                source_url=f"{detail.reference_url}/commit/{detail.reference_commit_sha}",
                commit_sha=detail.reference_commit_sha,
                path=detail.candidate_path,
            )
        )

    limitations = [
        "Code similarity measures shared syntactic structures against the configured reference collection only.",
        "High similarity does NOT prove copying direction, intellectual property infringement, or lack of original effort.",
        "Reference collection is restricted to a curated corpus and is not an exhaustive index of public code.",
        "Common patterns, library conventions, and assignment templates naturally elevate similarity scores.",
    ]

    return SimilarityAnalysisResult(
        overlap_score=Measurement[float](value=overall_overlap_pct),
        matched_paths=matched_paths_details,
        reference_commit_links=sorted(matched_commit_urls),
        coverage_statistics={
            "candidate_files_analyzed": len(candidate_files),
            "candidate_tokens_analyzed": total_tokens_count,
            "reference_files_indexed": reference_index.indexed_files_count,
        },
        algorithm_version=ALGORITHM_VERSION,
        algorithm_configuration=algo_config,
        evidence=evidence_items,
        limitations=limitations,
    )
