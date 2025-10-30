#!/bin/bash
set -e  # exit on any error
echo "==> Starting Nija Trading Bot..."

# 1️⃣ Remove old shadow folders
SHADOW_FOLDERS=(
  "/opt/render/project/src/coinbase_advanced_py"
  "/opt/render/project/src/coinbase-advanced-py"
)
for folder in "${SHADOW_FOLDERS[@]}"; do
  if [ -d "$folder" ]; then
    echo "[NIJA] Moving local shadow folder $folder -> local_shadow_backups/"
    mkdir -p /opt/render/project/src/local_shadow_backups/
    mv "$folder" /opt/render/project/src/local_shadow_backups/
  fi
done

# 2️⃣ Activate virtual environment
echo "[NIJA] Activating venv..."
source /opt/render/project/src/.venv/bin/activate

# 3️⃣ Ensure dependencies installed
echo "[NIJA] Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r /opt/render/project/src/requirements.txt

# 4️⃣ Optional: verify coinbase client
python -c "import coinbase_advanced_py.client as c; print('[NIJA] Coinbase client available')" || echo "[NIJA] Coinbase client not found, will use DummyClient."

# 5️⃣ Start Gunicorn
echo "[NIJA] Starting Gunicorn..."
exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 1
