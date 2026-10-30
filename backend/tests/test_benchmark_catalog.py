import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models.entities import BenchmarkProject
from app.services.benchmark_catalog import (
    INITIAL_BENCHMARKS,
    build_benchmark_reference_index,
    seed_and_index_benchmarks,
)
from app.services.similarity import (
    compare_repository,
)


@pytest.fixture
def in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_initial_benchmark_catalog_specification():
    """Verify exactly 5 initial benchmark projects matching the 5 required categories."""
    assert len(INITIAL_BENCHMARKS) == 5
    categories = [b["category"] for b in INITIAL_BENCHMARKS]
    expected_categories = [
        "Platform Clone",
        "Backend Engineering",
        "Real-Time Application",
        "Low-Level Design",
        "Distributed Systems",
    ]
    assert categories == expected_categories
    for b in INITIAL_BENCHMARKS:
        assert b["repository_url"].startswith("https://github.com/")
        assert len(b["pinned_commit_sha"]) == 40
        assert b["primary_language"] in {"python", "javascript", "typescript"}
        assert b["license"] is not None


def test_seed_and_index_all_five_benchmarks(in_memory_db):
    """Verify seeding and indexing exactly 5 benchmark projects into database."""
    results = seed_and_index_benchmarks(in_memory_db)
    assert len(results) == 5
    for r in results:
        assert r["status"] == "completed"
        assert r["files_indexed"] > 0
        assert r["tokens_count"] > 0

    projects = in_memory_db.query(BenchmarkProject).all()
    assert len(projects) == 5

    # Verify building reference index from DB
    ref_index = build_benchmark_reference_index(in_memory_db)
    assert not ref_index.is_empty()
    assert len(ref_index.catalog_entries) == 5
    assert ref_index.indexed_files_count >= 10


def test_scenario_1_exact_copied_repository(in_memory_db, tmp_path, monkeypatch):
    """Test 1: Exact copied source code matches benchmark with high similarity."""
    seed_and_index_benchmarks(in_memory_db)
    ref_index = build_benchmark_reference_index(in_memory_db)

    # Candidate copies Netflix Clone Banner.jsx and Row.jsx
    catalog_root = Path(__file__).resolve().parent.parent / "benchmarks_catalog"
    banner_src = (catalog_root / "netflix_clone" / "src" / "components" / "Banner.jsx").read_text()
    row_src = (catalog_root / "netflix_clone" / "src" / "components" / "Row.jsx").read_text()

    workspace_id = str(uuid.uuid4())
    cand_ws = tmp_path / "workspaces" / workspace_id
    cand_ws.mkdir(parents=True)
    (cand_ws / "Banner.jsx").write_text(banner_src)
    (cand_ws / "Row.jsx").write_text(row_src)

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.similarity._get_candidate_repo_files",
        lambda ws, head: ["Banner.jsx", "Row.jsx"],
    )
    monkeypatch.setattr(
        "app.services.similarity.read_source_blob",
        lambda ws, head, path, runner=None: type(
            "BlobResult", (), {"skipped": False, "content": (cand_ws / path).read_text()}
        )(),
    )

    result = compare_repository(workspace_id, ref_index)
    assert result.overlap_score.value is not None
    assert result.overlap_score.value >= 90.0
    assert len(result.matched_paths) >= 2

    match = result.matched_paths[0]
    assert match.benchmark_project_name == "Netflix Clone"
    assert match.benchmark_category == "Platform Clone"
    assert "https://github.com/Subhampreet/Netflix-Clone-ReactJS" in match.reference_url


def test_scenario_2_renamed_files_and_identifiers(in_memory_db, tmp_path, monkeypatch):
    """Test 2: Renamed files and identifier modifications are caught by structural tokenization."""
    seed_and_index_benchmarks(in_memory_db)
    ref_index = build_benchmark_reference_index(in_memory_db)

    catalog_root = Path(__file__).resolve().parent.parent / "benchmarks_catalog"
    rate_limiter_src = (catalog_root / "url_shortener" / "app" / "rate_limiter.py").read_text()

    # Rename variables and function names: should still match structural tokens
    renamed_code = rate_limiter_src.replace("TokenBucketRateLimiter", "CustomLeakyBucketLimiter")
    renamed_code = renamed_code.replace("acquire", "request_access")
    renamed_code = renamed_code.replace("replenished", "refilled_tokens")

    workspace_id = str(uuid.uuid4())
    cand_ws = tmp_path / "workspaces" / workspace_id
    cand_ws.mkdir(parents=True)
    (cand_ws / "my_custom_limiter.py").write_text(renamed_code)

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.similarity._get_candidate_repo_files",
        lambda ws, head: ["my_custom_limiter.py"],
    )
    monkeypatch.setattr(
        "app.services.similarity.read_source_blob",
        lambda ws, head, path, runner=None: type(
            "BlobResult", (), {"skipped": False, "content": (cand_ws / path).read_text()}
        )(),
    )

    result = compare_repository(workspace_id, ref_index)
    assert result.overlap_score.value is not None
    assert result.overlap_score.value >= 70.0
    assert len(result.matched_paths) >= 1
    assert result.matched_paths[0].benchmark_project_name == "URL Shortener with Rate Limiter"


def test_scenario_3_slightly_modified_copied_code(in_memory_db, tmp_path, monkeypatch):
    """Test 3: Copied code with added comments and extra print statements."""
    seed_and_index_benchmarks(in_memory_db)
    ref_index = build_benchmark_reference_index(in_memory_db)

    catalog_root = Path(__file__).resolve().parent.parent / "benchmarks_catalog"
    parking_src = (catalog_root / "parking_lot" / "parking_lot.py").read_text()

    modified_code = (
        "# Custom corporate copyright notice\n"
        + parking_src.replace("hourly_rate: float = 20.0", "hourly_rate: float = 50.0")
        + "\nprint('Parking lot initialized successfully!')\n"
    )

    workspace_id = str(uuid.uuid4())
    cand_ws = tmp_path / "workspaces" / workspace_id
    cand_ws.mkdir(parents=True)
    (cand_ws / "parking_lot.py").write_text(modified_code)

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.similarity._get_candidate_repo_files",
        lambda ws, head: ["parking_lot.py"],
    )
    monkeypatch.setattr(
        "app.services.similarity.read_source_blob",
        lambda ws, head, path, runner=None: type(
            "BlobResult", (), {"skipped": False, "content": (cand_ws / path).read_text()}
        )(),
    )

    result = compare_repository(workspace_id, ref_index)
    assert result.overlap_score.value is not None
    assert result.overlap_score.value >= 60.0
    assert result.matched_paths[0].benchmark_category == "Low-Level Design"


def test_scenario_4_different_implementation_same_concept(in_memory_db, tmp_path, monkeypatch):
    """Test 4: Candidate independently implements parking lot using completely different design."""
    seed_and_index_benchmarks(in_memory_db)
    ref_index = build_benchmark_reference_index(in_memory_db)

    independent_code = """
class SimpleValetService:
    def __init__(self):
        self.capacity = 100
        self.cars = set()

    def park(self, car_id: str) -> bool:
        if len(self.cars) < self.capacity:
            self.cars.add(car_id)
            return True
        return False

    def retrieve(self, car_id: str) -> bool:
        if car_id in self.cars:
            self.cars.remove(car_id)
            return True
        return False
"""
    workspace_id = str(uuid.uuid4())
    cand_ws = tmp_path / "workspaces" / workspace_id
    cand_ws.mkdir(parents=True)
    (cand_ws / "valet.py").write_text(independent_code)

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.similarity._get_candidate_repo_files",
        lambda ws, head: ["valet.py"],
    )
    monkeypatch.setattr(
        "app.services.similarity.read_source_blob",
        lambda ws, head, path, runner=None: type(
            "BlobResult", (), {"skipped": False, "content": (cand_ws / path).read_text()}
        )(),
    )

    result = compare_repository(workspace_id, ref_index)
    # Different implementation shares only negligible syntax (< 15% overlap)
    assert (result.overlap_score.value or 0.0) < 15.0


def test_scenario_5_empty_benchmark_catalog_returns_unavailable(
    in_memory_db, tmp_path, monkeypatch
):
    """Test 5: Empty benchmark catalog returns UNAVAILABLE without asserting 0% similarity."""
    # Do NOT seed in_memory_db
    empty_index = build_benchmark_reference_index(in_memory_db)
    assert empty_index.is_empty()

    workspace_id = str(uuid.uuid4())
    cand_ws = tmp_path / "workspaces" / workspace_id
    cand_ws.mkdir(parents=True)
    (cand_ws / "main.py").write_text("print('test app')\n")

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.similarity._get_candidate_repo_files",
        lambda ws, head: ["main.py"],
    )
    monkeypatch.setattr(
        "app.services.similarity.read_source_blob",
        lambda ws, head, path, runner=None: type(
            "BlobResult", (), {"skipped": False, "content": (cand_ws / path).read_text()}
        )(),
    )

    result = compare_repository(workspace_id, empty_index)
    assert result.overlap_score.value is None
    assert "empty" in result.overlap_score.reason.lower()


def test_scenario_6_missing_candidate_repository(in_memory_db, tmp_path, monkeypatch):
    """Test 6: Missing candidate workspace produces FileNotFoundError."""
    seed_and_index_benchmarks(in_memory_db)
    ref_index = build_benchmark_reference_index(in_memory_db)

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        compare_repository("non-existent-workspace-id", ref_index)


def test_scenario_7_shared_boilerplate_minimal_code(in_memory_db, tmp_path, monkeypatch):
    """Test 7: Standard generic imports and empty framework boilerplate don't falsely match."""
    seed_and_index_benchmarks(in_memory_db)
    ref_index = build_benchmark_reference_index(in_memory_db)

    generic_boilerplate = """
import express from 'express';
const app = express();
app.listen(3000, () => console.log('Listening'));
"""
    workspace_id = str(uuid.uuid4())
    cand_ws = tmp_path / "workspaces" / workspace_id
    cand_ws.mkdir(parents=True)
    (cand_ws / "index.js").write_text(generic_boilerplate)

    monkeypatch.setattr("app.services.similarity.settings.storage_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.services.similarity._get_candidate_repo_files",
        lambda ws, head: ["index.js"],
    )
    monkeypatch.setattr(
        "app.services.similarity.read_source_blob",
        lambda ws, head, path, runner=None: type(
            "BlobResult", (), {"skipped": False, "content": (cand_ws / path).read_text()}
        )(),
    )

    result = compare_repository(workspace_id, ref_index)
    # Trivial generic boilerplate should not yield significant overlap
    assert (result.overlap_score.value or 0.0) < 15.0
