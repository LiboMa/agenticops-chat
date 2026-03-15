#!/bin/bash
# Standardized test runner for ClawOps
# Ensures consistent repo/branch/env/command across all team members
set -euo pipefail

REPO_DIR="/home/ubuntu/agenticops-chat"
VENV_DIR="$REPO_DIR/.venv"

cd "$REPO_DIR"

# Fail fast if wrong repo
EXPECTED_REMOTE="LiboMa/ClawOps"
ACTUAL_REMOTE=$(git remote -v | head -1)
if [[ "$ACTUAL_REMOTE" != *"$EXPECTED_REMOTE"* ]]; then
    echo "ERROR: wrong repo — expected $EXPECTED_REMOTE, got: $ACTUAL_REMOTE"
    exit 1
fi

echo "=== ClawOps Test Run ==="
echo "Date:   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "Repo:   $REPO_DIR"
echo "Branch: $(git branch --show-current)"
echo "HEAD:   $(git log --oneline -1)"
echo "========================"

# Activate venv
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    echo "Python: $(python --version) (venv)"
else
    echo "ERROR: venv not found at $VENV_DIR"
    echo "Run: python3 -m venv $VENV_DIR && pip install -r requirements.txt"
    exit 1
fi

# Write metadata header to results file
{
    echo "=== ClawOps Test Run ==="
    echo "Date:   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo "Repo:   $REPO_DIR"
    echo "Branch: $(git branch --show-current)"
    echo "HEAD:   $(git log --oneline -1)"
    echo "Python: $(python --version)"
    echo "========================"
    echo ""
} > "$REPO_DIR/test_results.txt"

# Run tests (append to results file + tee to stdout)
python -m pytest tests/ -q --tb=short "$@" 2>&1 | tee -a "$REPO_DIR/test_results.txt"

echo ""
echo "Results saved to: $REPO_DIR/test_results.txt"
