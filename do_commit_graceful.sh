#!/bin/bash
set -e

git add bot.py start.sh

git commit -m "Add graceful SIGTERM/SIGINT handlers to prevent Railway restart loops

- bot.py: Install signal handlers for SIGTERM/SIGINT to exit cleanly (exit 0)
- start.sh: Treat exit code 143 (SIGTERM) as graceful shutdown, not crash
- Prevents Railway from marking controlled stops as failures and restarting
- Ensures liquidation cycles can complete without platform killing mid-execution
- Fixes: Railway stopping container during startup liquidation phase"

git push origin main

echo "✅ Graceful shutdown fix deployed to Railway!"
