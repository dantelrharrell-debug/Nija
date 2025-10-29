#!/bin/bash
# Auto-start for Render, no manual terminal needed

# Activate virtualenv
source .venv/bin/activate

# Load .env automatically
export $(grep -v '^#' .env | xargs)

# Start Gunicorn with Flask app
gunicorn -b 0.0.0.0:10000 app:app
