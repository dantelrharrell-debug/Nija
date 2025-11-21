#!/bin/bash
set -e

# Ensure start_all.sh is executable (in case it's mounted from a volume)
if [ -f /app/start_all.sh ]; then
    chmod +x /app/start_all.sh
    exec /app/start_all.sh
else
    echo "Error: /app/start_all.sh not found"
    exit 1
fi
