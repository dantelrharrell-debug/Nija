#!/bin/bash
# Create virtual environment if it does not exist
python3 -m venv .venv || true
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Start Flask app with Gunicorn
gunicorn nija_bot_web:app --bind 0.0.0.0:${PORT:-5000}
