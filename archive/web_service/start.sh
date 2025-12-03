#!/bin/bash
set -e

echo "Starting Web Service..."
exec gunicorn app:app --bind 0.0.0.0:5000 --workers 1
