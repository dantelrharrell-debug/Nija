#!/usr/bin/env bash
set -euo pipefail

echo "Running prebuild checks..."

# Ensure repo-root pyproject exists
if [[ ! -f "pyproject.toml" ]]; then
  echo "ERROR: pyproject.toml not found at repo root."
  exit 1
fi

# Ensure pyproject has [tool.poetry]
if ! grep -q "^\[tool\.poetry\]" pyproject.toml; then
  echo "ERROR: repo pyproject.toml does not contain a [tool.poetry] section."
  exit 1
fi

# Warn if bot/requirements.txt exists (just informational)
if [[ -f "bot/requirements.txt" ]]; then
  echo "INFO: bot/requirements.txt detected — builds will use Poetry from repo root. Ensure this is intended."
fi

echo "Prebuild checks passed."
