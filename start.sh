#!/bin/bash
# start.sh

# --- Ensure virtual environment ---
source .venv/bin/activate

# --- Optional: write PEM key from Render secret ---
if [ -n "$COINBASE_PEM" ]; then
  echo "$COINBASE_PEM" > ./coinbase.pem
  export COINBASE_PEM_PATH="./coinbase.pem"
fi

# --- Start Gunicorn for Flask (if your bot has Flask endpoints) ---
gunicorn -b 0.0.0.0:10000 wsgi:app &

# --- Start trader loop ---
python3 nija_live_snapshot.py
