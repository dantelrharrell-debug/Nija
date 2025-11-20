#!/usr/bin/env bash
set -euo pipefail

echo "== START: prepare SSH key for git (if SSH_PRIVATE_KEY set) =="
if [ -n "${SSH_PRIVATE_KEY:-}" ]; then
  mkdir -p /root/.ssh
  # write the private key from the env var
  printf "%s\n" "$SSH_PRIVATE_KEY" > /root/.ssh/id_ed25519
  chmod 600 /root/.ssh/id_ed25519

  # make sure SSH uses the file and doesn't prompt
  ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null || true
  echo "✅ SSH private key written to /root/.ssh/id_ed25519 and known_hosts updated"
else
  echo "⚠️ SSH_PRIVATE_KEY not set — runtime git+ssh will fail if repo requires SSH access"
fi

# optional: ensure git is installed (we usually install already)
# apt-get install -y git || true

# Now install the private coinbase package via SSH
echo "⏳ Installing coinbase-advanced from GitHub via SSH..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir "git+ssh://git@github.com/coinbase/coinbase-advanced-python.git"

# Start bot and server as you were doing
echo "⚡ Starting trading worker in background..."
python3 nija_render_worker.py &

echo "🚀 Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info

#!/usr/bin/env bash
set -euo pipefail

LOGFILE="/tmp/start_all.log"
echo "== START_ALL.SH: $(date -u) ==" > "$LOGFILE"

# 1) basic env check
echo "ENV CHECK at $(date -u)" >> "$LOGFILE"
echo "GITHUB_PAT present? ${GITHUB_PAT:+YES}" >> "$LOGFILE" 2>&1
echo "COINBASE_API_KEY present? ${COINBASE_API_KEY:+YES}" >> "$LOGFILE" 2>&1
echo "COINBASE_API_SECRET present? ${COINBASE_API_SECRET:+YES}" >> "$LOGFILE" 2>&1
echo "COINBASE_PEM_CONTENT present? ${COINBASE_PEM_CONTENT:+YES}" >> "$LOGFILE" 2>&1

# fail early if no GITHUB_PAT (we need it to pip-install the SDK if not included)
if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Set GITHUB_PAT in Railway/Render environment and redeploy." | tee -a "$LOGFILE"
  cat "$LOGFILE" || true
  exit 1
fi

# 2) ensure pip & core deps are present and install coinbase-advanced at runtime (if needed)
echo "⏳ Installing coinbase-advanced from GitHub (runtime)..." | tee -a "$LOGFILE"
python3 -m pip install --upgrade pip setuptools wheel 2>&1 | tee -a "$LOGFILE"

# If coinbase_advanced is not installed, install it from GitHub using PAT
python3 - <<PY | tee -a "$LOGFILE"
import sys, subprocess, importlib
try:
    import coinbase_advanced
    print("coinbase_advanced already installed")
except Exception:
    pkg = f"git+https://{''+('' if len('${GITHUB_PAT}')==0 else '${GITHUB_PAT}')}@github.com/coinbase/coinbase-advanced-python.git"
    # fallback: use the environment variable above; construct command using shell interpolation
    cmd = ["python3", "-m", "pip", "install", "--no-cache-dir", f"git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"]
    print("running:", " ".join(cmd))
    subprocess.check_call(cmd)
PY
echo "✅ coinbase-advanced install step finished" | tee -a "$LOGFILE"

# 3) start the trading worker (background) and save logs
echo "⚡ Starting trading worker (background), logs -> /tmp/worker.log" | tee -a "$LOGFILE"
/usr/bin/env python3 nija_render_worker.py >> /tmp/worker.log 2>&1 &

WORKER_PID=$!
echo "worker pid: $WORKER_PID" | tee -a "$LOGFILE"
sleep 2

echo "Tail of /tmp/worker.log (first check):" | tee -a "$LOGFILE"
tail -n 200 /tmp/worker.log 2>/dev/null | tee -a "$LOGFILE"

# 4) start gunicorn (replace shell, so container PID 1 becomes gunicorn)
echo "🚀 Starting gunicorn..." | tee -a "$LOGFILE"
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
