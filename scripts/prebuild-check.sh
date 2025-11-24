#!/usr/bin/env bash
set -euo pipefail
echo "Running prebuild checks..."
if [[ ! -f "pyproject.toml" ]]; then
  echo "ERROR: pyproject.toml not found at repo root."
  exit 1
fi
if grep -q "^\[tool\.poetry\]" pyproject.toml; then
  echo "INFO: Poetry project detected."
else
  echo "INFO: No [tool.poetry] in pyproject.toml — will fall back to requirements files."
fi
echo "Prebuild checks passed."
