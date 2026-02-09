#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$SCRIPT_DIR/dist"
DOCKERFILE="$SCRIPT_DIR/Dockerfile"

passed=0
failed=0
failures=()

# ── Build wheel ─────────────────────────────────────────────────────

echo "==> Building wheel..."
rm -rf "$DIST_DIR"
uv build --project "$PROJECT_ROOT" --out-dir "$DIST_DIR" --wheel
echo ""

# ── Helpers ─────────────────────────────────────────────────────────

run_test() {
    local name="$1"
    local base_image="$2"
    local install_flags="$3"
    local pre_cmd="${4:-}"
    local post_cmd="${5:-initrunner --version}"

    echo "--- $name (${base_image}) ---"

    local build_args=(
        --build-arg "BASE_IMAGE=$base_image"
        --build-arg "INSTALL_FLAGS=$install_flags"
        --build-arg "PRE_CMD=$pre_cmd"
        --build-arg "POST_CMD=$post_cmd"
    )

    if [ -n "${OPENAI_API_KEY:-}" ]; then
        build_args+=(--build-arg "OPENAI_API_KEY=$OPENAI_API_KEY")
    fi

    if docker build --no-cache -f "$DOCKERFILE" "${build_args[@]}" "$SCRIPT_DIR" >/dev/null 2>&1; then
        echo "  PASS: $name"
        ((passed++)) || true
    else
        echo "  FAIL: $name"
        echo "  Re-running with output for debugging:"
        docker build --no-cache -f "$DOCKERFILE" "${build_args[@]}" "$SCRIPT_DIR" 2>&1 | tail -40
        ((failed++)) || true
        failures+=("$name")
    fi
    echo ""
}

# ── Copy installer into build context ───────────────────────────────

cp "$PROJECT_ROOT/install.sh" "$SCRIPT_DIR/install.sh"
cp "$PROJECT_ROOT/examples/roles/hello-world.yaml" "$SCRIPT_DIR/hello-world.yaml"
trap 'rm -f "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/hello-world.yaml"' EXIT

# ── Scenarios ───────────────────────────────────────────────────────

should_run() {
    [ $# -eq 0 ] || [ "$1" = "$2" ]
}

FILTER="${1:-}"

if should_run "$FILTER" "auto-ubuntu"; then
    run_test "auto-ubuntu" \
        "ubuntu:24.04" \
        "--unmanaged"
fi

if should_run "$FILTER" "method-pip"; then
    run_test "method-pip" \
        "python:3.12-slim" \
        "--unmanaged --method pip"
fi

if should_run "$FILTER" "method-pipx"; then
    run_test "method-pipx" \
        "python:3.12-slim" \
        "--unmanaged --method pipx" \
        "pip install pipx"
fi

if should_run "$FILTER" "extras"; then
    run_test "extras" \
        "python:3.12-slim" \
        "--unmanaged --extras tui"
fi

if should_run "$FILTER" "uninstall"; then
    run_test "uninstall" \
        "python:3.12-slim" \
        "--unmanaged" \
        "" \
        "initrunner --version && sh /tmp/install.sh --uninstall && ! command -v initrunner"
fi

if should_run "$FILTER" "e2e-hello"; then
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "--- e2e-hello (SKIPPED: OPENAI_API_KEY not set) ---"
        echo ""
    else
        run_test "e2e-hello" \
            "ubuntu:24.04" \
            "--unmanaged" \
            "" \
            "initrunner run /tmp/hello-world.yaml -p 'Say hello'"
    fi
fi

# ── Summary ─────────────────────────────────────────────────────────

echo "==========================================="
echo "  Results: $passed passed, $failed failed"
if [ ${#failures[@]} -gt 0 ]; then
    echo "  Failed: ${failures[*]}"
fi
echo "==========================================="

exit "$failed"
