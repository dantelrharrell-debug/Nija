#!/usr/bin/env bash
set -euo pipefail

echo "[NIJA] Starting web service..."

# Do NOT install coinbase-advanced here. The bot service will install it.
exec gunicorn -w 1 -b 0.0.0.0:${PORT:-5000} main:app --log-level info
