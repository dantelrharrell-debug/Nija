#!/bin/bash
set -e  # Exit immediately if a command fails

# 1️⃣ Run pre-start checks
python pre_start.py

# 2️⃣ Start Gunicorn
echo "[INFO] Starting Gunicorn..."
exec gunicorn -c ./gunicorn.conf.py wsgi:app
