#!/bin/bash
# One-line deploy for Codespaces/Render/Railway

# Activate virtual environment or create if missing
source .venv/bin/activate || python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start Flask server with Gunicorn
gunicorn nija_bot_web:app --bind 0.0.0.0:$PORT
