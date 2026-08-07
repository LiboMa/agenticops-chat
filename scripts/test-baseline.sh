#!/usr/bin/env bash
# test-baseline.sh — Clean-tree test count for daily reports
# Always run from repo root; ensures no untracked/stashed files inflate count.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Guard: abort if working tree is dirty
if [[ -n "$(git status --porcelain tests/)" ]]; then
  echo "ERROR: tests/ directory is not clean. Untracked or modified files detected:" >&2
  git status --short tests/ >&2
  exit 1
fi

# Activate venv
source .venv/bin/activate

# Run pytest with clean cache
python -m pytest tests/ --cache-clear -q --tb=no 2>&1 | tail -3
