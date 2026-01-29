#!/usr/bin/env bash
set -euo pipefail
# Force-exit all positions even when EMERGENCY STOP is active.
# Creates override flags in the repo root so the bot will close all positions
# on the next trading cycle without needing environment variables.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Create override flags
: > FORCE_EXIT_OVERRIDE.conf
: > FORCE_EXIT_ALL.conf

echo "[force_exit_all] Flags set at $ROOT_DIR:"
echo "  - FORCE_EXIT_OVERRIDE.conf"
echo "  - FORCE_EXIT_ALL.conf"

echo "Bot will force-exit all positions on the next cycle, even in sell-only mode."
