#!/bin/bash
echo "=== STARTING NIJA TRADING BOT ==="
# Run Flask/Gunicorn
exec gunicorn app:app --bind 0.0.0.0:5000 --workers 2
