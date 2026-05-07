#!/usr/bin/env bash
set -euo pipefail

python scripts/compliance_scan.py
echo "Prebuild checks passed."
