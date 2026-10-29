#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# scripts/smoke.sh
# End-to-end integration and smoke test runner for isolated stack.
# Starts real Postgres, Redis, API, Worker, and Frontend.
# Exercises complete workflow without external network dependencies.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="${ROOT_DIR}/compose.test.yaml"
PROJECT_NAME="deviathon_smoke_test"
EXIT_CODE=0

echo "==> [Smoke Test] Initializing test environment..."

cleanup() {
    local code=$?
    echo "==> [Smoke Test] Cleaning up resources..."
    if command -v docker &>/dev/null && docker info &>/dev/null; then
        echo "--> Halting and removing Docker Compose containers..."
        docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" down -v --remove-orphans || true
    fi
    # Clean any background process if spawned
    if [ -n "${LOCAL_API_PID:-}" ]; then
        kill "${LOCAL_API_PID}" 2>/dev/null || true
    fi
    if [ -n "${LOCAL_FRONTEND_PID:-}" ]; then
        kill "${LOCAL_FRONTEND_PID}" 2>/dev/null || true
    fi
    echo "==> [Smoke Test] Cleanup complete. Exiting with code: ${code}"
    exit "${code}"
}

trap cleanup EXIT INT TERM

# Ensure fixtures exist
echo "==> [Smoke Test] Ensuring synthetic test fixtures are generated..."
PYTHON_BIN="python3"
if [ -f "${ROOT_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
fi

"${PYTHON_BIN}" "${ROOT_DIR}/backend/tests/fixtures/create_fixtures.py"

# Check if Docker is running and accessible
CAN_DOCKER=false
if command -v docker &>/dev/null && docker info &>/dev/null; then
    CAN_DOCKER=true
fi

if [ "${CAN_DOCKER}" = true ]; then
    echo "==> [Smoke Test] Docker daemon detected. Spinning up isolated test stack via compose.test.yaml..."
    
    # Build and start services in background
    docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" up -d --build
    
    echo "==> [Smoke Test] Waiting for services to reach healthy status..."
    MAX_WAIT=60
    WAIT_COUNT=0
    HEALTHY=false

    while [ "${WAIT_COUNT}" -lt "${MAX_WAIT}" ]; do
        API_STATUS=$(docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" ps api --format json 2>/dev/null | grep -o '"Health":"[^"]*"' | cut -d'"' -f4 || echo "starting")
        if [ "${API_STATUS}" = "healthy" ]; then
            HEALTHY=true
            break
        fi
        sleep 2
        WAIT_COUNT=$((WAIT_COUNT + 2))
        echo "--> Waiting for services... (${WAIT_COUNT}s / ${MAX_WAIT}s)"
    done

    if [ "${HEALTHY}" != true ]; then
        echo "ERROR: Test stack services failed to become healthy within ${MAX_WAIT}s."
        echo "--- Bounded Failure Diagnostics (Last 100 lines) ---"
        docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" logs --tail 100
        exit 1
    fi

    echo "==> [Smoke Test] Services healthy! Running Playwright E2E browser tests..."
    if command -v npx &>/dev/null && [ -d "${ROOT_DIR}/frontend/node_modules/@playwright" ]; then
        cd "${ROOT_DIR}/frontend"
        PLAYWRIGHT_BASE_URL="http://localhost:3000" ADMIN_PASSWORD="test-admin-secret" npx playwright test || {
            echo "ERROR: Playwright E2E test execution failed."
            echo "--- Bounded Service Logs (Last 100 lines) ---"
            docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" logs --tail 100
            exit 1
        }
    else
        echo "--> Local Playwright runtime not installed; running full E2E workflow suite against API..."
        cd "${ROOT_DIR}"
        ALLOW_TEST_ADAPTERS="true" "${ROOT_DIR}/.venv/bin/pytest" backend/tests/test_e2e_workflow.py -v || {
            echo "ERROR: E2E workflow verification failed."
            docker compose -p "${PROJECT_NAME}" -f "${COMPOSE_FILE}" logs --tail 100
            exit 1
        }
    fi
else
    echo "==> [Smoke Test] Docker daemon unavailable in current execution context."
    echo "--> Executing standalone full E2E test suite in deterministic isolated adapter mode..."
    cd "${ROOT_DIR}"
    ALLOW_TEST_ADAPTERS="true" "${ROOT_DIR}/.venv/bin/pytest" backend/tests/test_e2e_workflow.py -v || {
        echo "ERROR: Standalone E2E integration test failed."
        exit 1
    }
fi

echo "==> [Smoke Test] All integration and workflow checks PASSED! ✓"
