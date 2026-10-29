#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# scripts/check.sh
# Comprehensive release checks: backend tests, frontend checks, OpenAPI drift
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

echo "==> [1/5] Backend Lint & Code Hygiene Check..."
if command -v ruff &>/dev/null; then
    ruff check backend
elif [ -f "${ROOT_DIR}/.venv/bin/ruff" ]; then
    "${ROOT_DIR}/.venv/bin/ruff" check backend
else
    python3 -m ruff check backend || echo "Warning: ruff not available, skipping lint check."
fi

echo "==> [2/5] Backend Test Suite Execution..."
if [ -f "${ROOT_DIR}/.venv/bin/pytest" ]; then
    "${ROOT_DIR}/.venv/bin/pytest" backend/tests -q
else
    python3 -m pytest backend/tests -q
fi

echo "==> [3/5] OpenAPI Drift Validation..."
PYTHON_BIN="python3"
if [ -f "${ROOT_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

PYTHONPATH=backend "${PYTHON_BIN}" -c '
import json, sys
from app.main import app

committed_path = "backend/openapi.json"
try:
    with open(committed_path, "r", encoding="utf-8") as f:
        committed = json.load(f)
except Exception as e:
    sys.stderr.write(f"ERROR: Failed reading {committed_path}: {e}\n")
    sys.exit(1)

current = app.openapi()
if current != committed:
    sys.stderr.write("ERROR: OpenAPI schema drift detected! The current FastAPI app schema differs from backend/openapi.json.\n")
    sys.stderr.write("Run scripts/export_openapi.py or update backend/openapi.json to sync.\n")
    sys.exit(1)

print("✓ OpenAPI schema matches backend/openapi.json exactly.")
'

echo "==> [4/5] Frontend Unit & Component Tests..."
npm --prefix frontend test -- --run

echo "==> [5/5] Frontend Typecheck & Production Build..."
npm --prefix frontend run build

echo "==> ALL PRE-RELEASE CHECKS PASSED SUCCESSFULLY! ✓"
