import subprocess
import uuid

import pytest

from app.config import settings
from app.services.reference_catalog import CatalogEntry, load_reference_catalog
from app.services.repository_fetcher import fetch_repository
from app.services.similarity import (
    ReferenceIndex,
    build_reference_index,
    compare_repository,
    compute_winnowing_fingerprints,
    tokenize_source,
)


def test_catalog_entry_validation():
    # Valid pinned entry
    entry = CatalogEntry(
        repository_url="https://github.com/reference-org/base-algo",
        pinned_commit_sha="0123456789abcdef0123456789abcdef01234567",
        language="python",
        license="MIT",
        selection_rationale="Reference implementation of binary search tree",
    )
    assert entry.language == "python"

    # Reject unpinned commit SHA (e.g., branch name or short hash)
    with pytest.raises(ValueError, match="must specify a pinned 40-character commit SHA"):
        CatalogEntry(
            repository_url="https://github.com/reference-org/base-algo",
            pinned_commit_sha="main",
            language="python",
            license="MIT",
            selection_rationale="Unpinned branch",
        )

    with pytest.raises(ValueError, match="must specify a pinned 40-character commit SHA"):
        CatalogEntry(
            repository_url="https://github.com/reference-org/base-algo",
            pinned_commit_sha="abc123",
            language="python",
            license="MIT",
            selection_rationale="Short hash",
        )

    # Reject invalid repository URL
    with pytest.raises(ValueError, match="Invalid repository URL"):
        CatalogEntry(
            repository_url="https://gitlab.com/reference-org/base-algo",
            pinned_commit_sha="0123456789abcdef0123456789abcdef01234567",
            language="python",
            license="MIT",
            selection_rationale="Invalid host",
        )


def test_production_catalog_is_empty():
    catalog = load_reference_catalog()
    assert isinstance(catalog, list)
    assert len(catalog) == 0


@pytest.fixture
def sample_reference_entry():
    return CatalogEntry(
        repository_url="https://github.com/reference-org/data-structures",
        pinned_commit_sha="a1b2c3d4e5f60123456789abcdef0123456789ab",
        language="python",
        license="MIT",
        selection_rationale="Curated standard library implementation",
    )


REFERENCE_SORT_CODE = """
def quick_sort(items):
    if len(items) <= 1:
        return items
    pivot = items[len(items) // 2]
    left = [x for x in items if x < pivot]
    middle = [x for x in items if x == pivot]
    right = [x for x in items if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)

def partition(arr, low, high):
    pivot = arr[high]
    i = low - 1
    for j in range(low, high):
        if arr[j] <= pivot:
            i = i + 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1
"""

RENAMED_SORT_CODE = """
def custom_sort(elements):
    if len(elements) <= 1:
        return elements
    center = elements[len(elements) // 2]
    lesser = [val for val in elements if val < center]
    equal = [val for val in elements if val == center]
    greater = [val for val in elements if val > center]
    return custom_sort(lesser) + equal + custom_sort(greater)

def split_segment(vector, start, finish):
    key = vector[finish]
    idx = start - 1
    for pos in range(start, finish):
        if vector[pos] <= key:
            idx = idx + 1
            vector[idx], vector[pos] = vector[pos], vector[idx]
    vector[idx + 1], vector[finish] = vector[finish], vector[idx + 1]
    return idx + 1
"""

UNRELATED_CODE = """
class WebServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.routes = {}

    def add_route(self, path, handler):
        self.routes[path] = handler

    def listen(self):
        print(f"Server listening on {self.host}:{self.port}")
"""


def test_tokenization_and_renamed_identifiers_match():
    tokens_orig = tokenize_source(REFERENCE_SORT_CODE, "python")
    tokens_renamed = tokenize_source(RENAMED_SORT_CODE, "python")

    # Identifiers normalized to _ID_, so token stream values should match
    vals_orig = [t[0] for t in tokens_orig]
    vals_renamed = [t[0] for t in tokens_renamed]
    assert vals_orig == vals_renamed

    fps_orig = compute_winnowing_fingerprints(tokens_orig)
    fps_renamed = compute_winnowing_fingerprints(tokens_renamed)

    assert len(fps_orig) > 0
    assert [f[0] for f in fps_orig] == [f[0] for f in fps_renamed]


def test_exact_matches_in_repository(sample_reference_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    # 1. Build reference index with reference code
    ref_index = build_reference_index([sample_reference_entry])
    ref_index.add_reference_file(sample_reference_entry, "src/sort.py", REFERENCE_SORT_CODE)

    # 2. Build candidate repo with identical code
    candidate_dir = tmp_path / "candidate_repo"
    candidate_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=candidate_dir, check=True)
    (candidate_dir / "algorithms.py").write_text(REFERENCE_SORT_CODE)
    subprocess.run(["git", "add", "."], cwd=candidate_dir, check=True)
    subprocess.run(["git", "commit", "-m", "add algo"], cwd=candidate_dir, check=True)

    manifest = fetch_repository(str(candidate_dir), job_id=uuid.uuid4(), allow_file_transport=True)

    # 3. Compare
    result = compare_repository(manifest, ref_index)
    assert result.overlap_score.value is not None
    assert result.overlap_score.value > 90.0
    assert len(result.matched_paths) == 1
    assert result.matched_paths[0].candidate_path == "algorithms.py"
    assert result.matched_paths[0].reference_url == sample_reference_entry.repository_url
    assert len(result.reference_commit_links) == 1
    assert any("does NOT prove copying" in lim for lim in result.limitations)


def test_renamed_identifiers_in_repository(sample_reference_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    ref_index = build_reference_index([sample_reference_entry])
    ref_index.add_reference_file(sample_reference_entry, "src/sort.py", REFERENCE_SORT_CODE)

    candidate_dir = tmp_path / "renamed_repo"
    candidate_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=candidate_dir, check=True)
    (candidate_dir / "my_sort.py").write_text(RENAMED_SORT_CODE)
    subprocess.run(["git", "add", "."], cwd=candidate_dir, check=True)
    subprocess.run(["git", "commit", "-m", "add renamed algo"], cwd=candidate_dir, check=True)

    manifest = fetch_repository(str(candidate_dir), job_id=uuid.uuid4(), allow_file_transport=True)

    result = compare_repository(manifest, ref_index)
    assert result.overlap_score.value is not None
    assert result.overlap_score.value > 90.0
    assert result.matched_paths[0].candidate_path == "my_sort.py"


def test_unrelated_code_produces_zero_overlap(sample_reference_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    ref_index = build_reference_index([sample_reference_entry])
    ref_index.add_reference_file(sample_reference_entry, "src/sort.py", REFERENCE_SORT_CODE)

    candidate_dir = tmp_path / "unrelated_repo"
    candidate_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=candidate_dir, check=True)
    (candidate_dir / "server.py").write_text(UNRELATED_CODE)
    subprocess.run(["git", "add", "."], cwd=candidate_dir, check=True)
    subprocess.run(["git", "commit", "-m", "add server"], cwd=candidate_dir, check=True)

    manifest = fetch_repository(str(candidate_dir), job_id=uuid.uuid4(), allow_file_transport=True)

    result = compare_repository(manifest, ref_index)
    assert result.overlap_score.value == 0.0
    assert len(result.matched_paths) == 0


def test_boilerplate_and_vendor_exclusions(sample_reference_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))

    ref_index = build_reference_index([sample_reference_entry])
    ref_index.add_reference_file(sample_reference_entry, "src/sort.py", REFERENCE_SORT_CODE)

    candidate_dir = tmp_path / "boilerplate_repo"
    candidate_dir.mkdir()
    (candidate_dir / "node_modules").mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=candidate_dir, check=True)

    # Excluded files
    (candidate_dir / "node_modules" / "vendor.py").write_text(REFERENCE_SORT_CODE)
    (candidate_dir / "package-lock.json").write_text("{}")
    (candidate_dir / "app.bundle.js").write_text("console.log('bundled');")

    # Only 1 valid file with unrelated code
    (candidate_dir / "app.py").write_text(UNRELATED_CODE)

    subprocess.run(["git", "add", "."], cwd=candidate_dir, check=True)
    subprocess.run(["git", "commit", "-m", "add files"], cwd=candidate_dir, check=True)

    manifest = fetch_repository(str(candidate_dir), job_id=uuid.uuid4(), allow_file_transport=True)

    result = compare_repository(manifest, ref_index)
    # node_modules and bundle are excluded, only app.py analyzed
    assert result.coverage_statistics["candidate_files_analyzed"] == 1
    assert result.overlap_score.value == 0.0


def test_empty_catalog_produces_unavailable_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    empty_index = ReferenceIndex()  # Empty reference index

    candidate_dir = tmp_path / "repo1"
    candidate_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=candidate_dir, check=True)
    (candidate_dir / "main.py").write_text(REFERENCE_SORT_CODE)
    subprocess.run(["git", "add", "."], cwd=candidate_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=candidate_dir, check=True)

    manifest = fetch_repository(str(candidate_dir), job_id=uuid.uuid4(), allow_file_transport=True)

    result = compare_repository(manifest, empty_index)
    assert result.overlap_score.value is None
    assert result.overlap_score.reason is not None
    assert "Reference catalog collection is empty" in result.overlap_score.reason


def test_no_source_files_produces_unavailable_measurement(
    sample_reference_entry, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    ref_index = build_reference_index([sample_reference_entry])
    ref_index.add_reference_file(sample_reference_entry, "src/sort.py", REFERENCE_SORT_CODE)

    candidate_dir = tmp_path / "docs_only_repo"
    candidate_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=candidate_dir, check=True)
    (candidate_dir / "README.md").write_text("# Documentation only")
    subprocess.run(["git", "add", "."], cwd=candidate_dir, check=True)
    subprocess.run(["git", "commit", "-m", "docs only"], cwd=candidate_dir, check=True)

    manifest = fetch_repository(str(candidate_dir), job_id=uuid.uuid4(), allow_file_transport=True)

    result = compare_repository(manifest, ref_index)
    assert result.overlap_score.value is None
    assert result.overlap_score.reason is not None
    assert (
        "No analyzable Python or JavaScript/TypeScript source files" in result.overlap_score.reason
    )
