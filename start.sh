#!/usr/bin/env bash
set -euo pipefail

echo "[NIJA] start.sh: container startup"

# -> Required runtime envs
: "${GITHUB_PAT:?GITHUB_PAT must be set in env (secret)}"
# optional: choose mode: "web" (default) or "worker"
RUN_MODE="${RUN_MODE:-web}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Use python -m pip for reliability
echo "[NIJA] Upgrading pip + wheel + setuptools"
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel >/dev/null

# Install the Coinbase Advanced SDK from github at runtime (using your PAT)
# Retry a few times because network/git can be flaky on some builders
echo "[NIJA] Installing coinbase-advanced from GitHub (runtime install)"
MAX_TRIES=3
TRY=0
until [ "$TRY" -ge "$MAX_TRIES" ]; do
  if "$PYTHON_BIN" -m pip install --no-cache-dir --prefer-binary "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"; then
    echo "[NIJA] ✅ coinbase-advanced installed"
    break
  fi
  TRY=$((TRY + 1))
  echo "[NIJA] install failed, attempt $TRY/$MAX_TRIES — sleeping before retry"
  sleep $((TRY * 2))
done

if [ "$TRY" -ge "$MAX_TRIES" ]; then
  echo "[NIJA] ❌ Failed to install coinbase-advanced after $MAX_TRIES attempts"
  exit 1
fi

# Optional: install other runtime-only packages (if any)
# "$PYTHON_BIN" -m pip install --no-cache-dir other-package

# Start appropriate process
if [ "$RUN_MODE" = "worker" ]; then
  echo "[NIJA] Starting worker: nija_render_worker.py"
  exec "$PYTHON_BIN" nija_render_worker.py
else
  echo "[NIJA] Starting web (gunicorn) — expecting Flask app at main:app"
  # 1 worker - change -w count if needed; add timeout etc. as required
  exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
fi
