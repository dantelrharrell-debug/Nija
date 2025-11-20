#!/usr/bin/env bash
set -euo pipefail
echo "[WEB] Starting web service (gunicorn)..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
