#!/usr/bin/env python3
"""
Generates synthetic test fixtures:
1. Bare Git repository with multiple commits, authors, and source code files.
2. Synthetic PDF resume with candidate name, project, and GitHub URL.
3. Synthetic DOCX resume with second candidate and inaccessible project.
4. Corrupt PDF file to test partial batch upload rejection.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import docx
import pymupdf


def create_synthetic_git_repo(output_dir: Path) -> Path:
    target_bare_dir = output_dir / "synthetic_repos" / "portfolio-app.git"
    if target_bare_dir.exists():
        shutil.rmtree(target_bare_dir, ignore_errors=True)
    target_bare_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_repo:
        repo_path = Path(temp_repo)

        # 1. git init
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Alex Mercer"], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "config", "user.email", "alex.mercer@example.org"], cwd=repo_path, check=True
        )

        # 2. Commit 1: Initial commit by candidate
        (repo_path / "README.md").write_text(
            "# Portfolio App\nA web application for demonstrating project work.\n"
        )
        (repo_path / "main.py").write_text(
            '"""Main web service module."""\n\ndef run_server():\n    print("Starting server...")\n\nif __name__ == "__main__":\n    run_server()\n'
        )
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit: basic service skeleton"],
            cwd=repo_path,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": "2024-01-15T10:00:00Z",
                "GIT_COMMITTER_DATE": "2024-01-15T10:00:00Z",
            },
            check=True,
            capture_output=True,
        )

        # 3. Commit 2: Secondary contributor commit
        (repo_path / "utils.py").write_text(
            '"""Utility functions."""\n\ndef parse_config(filepath):\n    return {"port": 8080, "host": "0.0.0.0"}\n'
        )
        subprocess.run(["git", "add", "utils.py"], cwd=repo_path, check=True)
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Add configuration utilities",
                "--author",
                "Sam Taylor <sam.taylor@example.org>",
            ],
            cwd=repo_path,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": "2024-02-01T14:30:00Z",
                "GIT_COMMITTER_DATE": "2024-02-01T14:30:00Z",
            },
            check=True,
            capture_output=True,
        )

        # 4. Commit 3: Second candidate commit
        (repo_path / "main.py").write_text(
            '"""Main web service module with router."""\n\nfrom utils import parse_config\n\ndef run_server():\n    cfg = parse_config("config.json")\n    print(f"Listening on {cfg[\'port\']}")\n\nif __name__ == "__main__":\n    run_server()\n'
        )
        subprocess.run(["git", "add", "main.py"], cwd=repo_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Integrate config parser and improve logging"],
            cwd=repo_path,
            env={
                **os.environ,
                "GIT_AUTHOR_DATE": "2024-03-10T09:15:00Z",
                "GIT_COMMITTER_DATE": "2024-03-10T09:15:00Z",
            },
            check=True,
            capture_output=True,
        )

        # 5. Clone as bare repository into target
        subprocess.run(
            ["git", "clone", "--bare", str(repo_path), str(target_bare_dir)],
            check=True,
            capture_output=True,
        )

    return target_bare_dir


def create_synthetic_resumes(output_dir: Path) -> dict[str, Path]:
    resumes_dir = output_dir / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)

    # 1. Valid PDF resume (Alex Mercer)
    pdf_path = resumes_dir / "alex_mercer_portfolio.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    text = (
        "Alex Mercer\n"
        "alex.mercer@example.org | (555) 019-2834 | San Francisco, CA\n\n"
        "PROFESSIONAL SUMMARY\n"
        "Senior Software Engineer specializing in Python and distributed systems.\n\n"
        "PROJECTS\n"
        "Portfolio App\n"
        "Developed high-throughput API service in Python with modular architecture.\n"
        "Repository: https://github.com/synthetic-candidate/portfolio-app\n\n"
        "EXPERIENCE\n"
        "Lead Engineer at Acme Tech (2020 - Present)\n"
    )
    page.insert_text((50, 50), text, fontsize=11)
    doc.save(str(pdf_path))
    doc.close()

    # 2. Valid DOCX resume (Jordan Lee)
    docx_path = resumes_dir / "jordan_lee_inaccessible.docx"
    doc_docx = docx.Document()
    doc_docx.add_heading("Jordan Lee", level=0)
    doc_docx.add_paragraph("jordan.lee@example.org | Systems Developer")
    doc_docx.add_heading("Key Projects", level=1)
    doc_docx.add_paragraph(
        "Inaccessible App: Proprietary backend automation toolkit.\n"
        "Repository: https://github.com/synthetic-candidate/inaccessible-repo"
    )
    doc_docx.save(str(docx_path))

    # 3. Corrupt file to test partial batch failure
    corrupt_path = resumes_dir / "corrupt_resume.pdf"
    corrupt_path.write_bytes(b"INVALID_HEADER_NOT_A_REAL_PDF_DOCUMENT_12345")

    return {
        "pdf": pdf_path,
        "docx": docx_path,
        "corrupt": corrupt_path,
    }


def main():
    fixtures_dir = Path(__file__).resolve().parent
    print(f"Generating synthetic fixtures in {fixtures_dir}...")
    repo = create_synthetic_git_repo(fixtures_dir)
    print(f"Created synthetic bare repository: {repo}")
    resumes = create_synthetic_resumes(fixtures_dir)
    for k, v in resumes.items():
        print(f"Created synthetic resume [{k}]: {v}")
    print("All fixtures generated successfully.")


if __name__ == "__main__":
    main()
