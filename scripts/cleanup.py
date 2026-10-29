#!/usr/bin/env python3
"""
Runnable data retention cleanup command.
Enforces data retention policies by purging expired resumes, candidate records,
canceled jobs, and temporary workspaces.
"""
import argparse
import sys
from pathlib import Path

# Ensure backend directory is in python path
backend_path = Path(__file__).resolve().parent.parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.db import SessionLocal
from app.services.retention import run_retention_cleanup


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run automated data retention and privacy cleanup."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Retention period in days (default: configured in settings, usually 7)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate cleanup without deleting database records or files",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute actual deletion of expired records and files",
    )

    args = parser.parse_args()
    is_dry_run = args.dry_run or (not args.execute)

    db = SessionLocal()
    try:
        summary = run_retention_cleanup(db=db, days=args.days, dry_run=is_dry_run)
        mode = "DRY-RUN" if summary.dry_run else "EXECUTE"
        print(f"[{mode}] Retention cleanup completed:")
        print(f"  Cutoff Date:         {summary.cutoff_date}")
        print(f"  Candidates Removed:  {summary.candidates_deleted}")
        print(f"  Resumes Purged:      {summary.resumes_deleted}")
        print(f"  Jobs Cancelled:      {summary.jobs_cancelled}")
        print(f"  Workspaces Cleaned:  {summary.workspaces_deleted}")
        return 0
    except Exception as e:
        print(f"Error during retention cleanup: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
