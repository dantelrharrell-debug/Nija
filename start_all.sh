#!/usr/bin/env bash
set -euo pipefail

LOGFILE="/tmp/start_all.log"
echo "== START_ALL.SH: $(date -u) ==" > "$LOGFILE"
echo "ENV CHECK: GITHUB_PAT present? ${GITHUB_PAT:+YES}" >> "$LOGFILE" 2>&1

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Aborting. (Set it in Railway/Render secrets)" | tee -a "$LOGFILE"
  exit 1
fi

echo "⏳ Installing coinbase-advanced from GitHub..." | tee -a "$LOGFILE"
python3 -m pip install --upgrade pip setuptools wheel 2>&1 | tee -a "$LOGFILE"

if ! python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git" 2>&1 | tee -a "$LOGFILE"; then
  echo "❌ Failed to install coinbase-advanced. See $LOGFILE for details." | tee -a "$LOGFILE"
  tail -n 200 "$LOGFILE" || true
  exit 1
fi

echo "✅ coinbase-advanced installed" | tee -a "$LOGFILE"

echo "⚡ Starting trading worker (background)..." | tee -a "$LOGFILE"
python3 nija_render_worker.py >> /tmp/worker.log 2>&1 &

sleep 1
echo "worker pid: $!" | tee -a "$LOGFILE"
echo "Tail of worker log:" | tee -a "$LOGFILE"
tail -n 50 /tmp/worker.log 2>/dev/null | tee -a "$LOGFILE"

echo "🚀 Starting Gunicorn..." | tee -a "$LOGFILE"
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
