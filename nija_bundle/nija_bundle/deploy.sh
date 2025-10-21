#!/bin/bash
source .venv/bin/activate || python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gunicorn nija_bot_web:app --bind 0.0.0.0:${PORT:-5000}
